// Face ID Unlock Helper: when the Mac wakes to a locked screen, checks your face and, if it
// matches, types your login password (kept in your Keychain) into the lock screen.
//
//   helper run              background agent (started by launchd, see agent.sh)
//   helper set-password     read the password from stdin, verify it, save it to the Keychain
//   helper clear-password   delete it from the Keychain
//   helper status           print {"password_saved": bool}
import AVFoundation
import AppKit
import ApplicationServices
import OpenDirectory
import Security

let keychainService = "local.faceidunlock.login-password"
let account = NSUserName()
let home = FileManager.default.homeDirectoryForCurrentUser
// Bundle lives at <project>/face_unlock/Face ID Unlock Helper.app
let project = Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent()
let configURL = project.appendingPathComponent("face_unlock/config.json")
let statusURL = home.appendingPathComponent("Library/Application Support/FaceIDUnlock/status.json")
let logURL = home.appendingPathComponent("Library/Logs/FaceIDUnlockHelper.log")

// MARK: Keychain

let keychainQuery: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: keychainService,
    kSecAttrAccount as String: account,
]

func savePassword(_ password: String) -> Bool {
    SecItemDelete(keychainQuery as CFDictionary)
    var item = keychainQuery
    item[kSecValueData as String] = Data(password.utf8)
    item[kSecAttrLabel as String] = "Face ID Unlock (Mac login password)"
    return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
}

func loadPassword() -> String? {
    var query = keychainQuery
    query[kSecReturnData as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: AnyObject?
    guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
          let data = result as? Data else { return nil }
    return String(data: data, encoding: .utf8)
}

func passwordSaved() -> Bool {
    var query = keychainQuery
    query[kSecReturnAttributes as String] = true
    return SecItemCopyMatching(query as CFDictionary, nil) == errSecSuccess
}

/// Checks the password against the local account so a typo is never typed at the lock screen.
func isCorrectPassword(_ password: String) -> Bool {
    guard let node = try? ODNode(session: ODSession.default(), type: ODNodeType(kODNodeTypeLocalNodes)),
          let record = try? node.record(withRecordType: kODRecordTypeUsers, name: account, attributes: nil)
    else { return false }
    do {
        try record.verifyPassword(password)
        return true
    } catch {
        return false
    }
}

// MARK: Session, typing, face check

func screenIsLocked() -> Bool {
    guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
    let locked = (session["CGSSessionScreenIsLocked"] as? Bool) ?? false
    let onConsole = (session["kCGSSessionOnConsoleKey"] as? Bool) ?? false
    return locked && onConsole
}

/// Types into the lock screen, stopping at once if the screen is no longer locked,
/// so the password can never end up in a normal window.
func typeIntoLockScreen(_ text: String) -> Bool {
    let source = CGEventSource(stateID: .hidSystemState)
    for unit in text.utf16 {
        guard screenIsLocked() else { return false }
        for down in [true, false] {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down) else { return false }
            var c = unit
            event.keyboardSetUnicodeString(stringLength: 1, unicodeString: &c)
            event.post(tap: .cghidEventTap)
            usleep(6_000)
        }
    }
    guard screenIsLocked() else { return false }
    for down in [true, false] {
        CGEvent(keyboardEventSource: source, virtualKey: 36, keyDown: down)?.post(tap: .cghidEventTap)  // Return
    }
    return true
}

/// True if you touched the keyboard, trackpad or mouse after `date`.
func userInputSince(_ date: Date) -> Bool {
    let anyInput = CGEventType(rawValue: ~0)!
    let idle = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: anyInput)
    return idle < Date().timeIntervalSince(date)
}

/// Waits until the display is on, then nudges the lock screen with Shift (types nothing) so
/// the password box is awake. Keys typed while the display is asleep are dropped, which is
/// what made earlier attempts send an incomplete password. Returns when Shift was pressed,
/// or nil if the lock screen never became ready.
func lockScreenReady(settle: Double) -> Date? {
    var waited = 0.0
    while CGDisplayIsAsleep(CGMainDisplayID()) != 0 && waited < 10 {
        Thread.sleep(forTimeInterval: 0.05)
        waited += 0.05
    }
    guard CGDisplayIsAsleep(CGMainDisplayID()) == 0 else { return nil }
    let source = CGEventSource(stateID: .hidSystemState)
    let pressed = Date()
    for down in [true, false] {
        CGEvent(keyboardEventSource: source, virtualKey: 56, keyDown: down)?.post(tap: .cghidEventTap)  // Shift
    }
    Thread.sleep(forTimeInterval: settle)
    return CGDisplayIsAsleep(CGMainDisplayID()) == 0 && screenIsLocked() ? pressed : nil
}

/// Selects and deletes whatever is in the password box (Command-A, Delete).
func clearPasswordBox() {
    let source = CGEventSource(stateID: .hidSystemState)
    for down in [true, false] {
        let selectAll = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down)  // A
        selectAll?.flags = .maskCommand
        selectAll?.post(tap: .cghidEventTap)
    }
    for down in [true, false] {
        CGEvent(keyboardEventSource: source, virtualKey: 51, keyDown: down)?.post(tap: .cghidEventTap)  // Delete
    }
    usleep(100_000)
}

func waitForUnlock(within seconds: Double) -> Bool {
    var waited = 0.0
    while screenIsLocked() && waited < seconds {
        Thread.sleep(forTimeInterval: 0.1)
        waited += 0.1
    }
    return !screenIsLocked()
}

struct Config {
    var enabled = false
    var timeout = 8.0

    static func load() -> Config {
        guard let data = try? Data(contentsOf: configURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return Config() }
        return Config(enabled: json["enabled"] as? Bool ?? false,
                      timeout: (json["timeout_seconds"] as? NSNumber)?.doubleValue ?? 8)
    }
}

func faceMatches(timeout: Double) -> Bool {
    let process = Process()
    process.executableURL = project.appendingPathComponent(".venv/bin/python")
    process.arguments = [
        "-I", project.appendingPathComponent("face_sudo/check_face.py").path,
        "--config", configURL.path,
        "--faces", project.appendingPathComponent("face_vault/data/owner_embeddings.npy").path,
        "--models", home.appendingPathComponent(".insightface").path,
    ]
    process.standardInput = FileHandle.nullDevice
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    do { try process.run() } catch {
        log("could not start face check: \(error)")
        return false
    }
    // The checker stops itself at its own timeout; this is a backstop.
    DispatchQueue.global().asyncAfter(deadline: .now() + timeout + 8) {
        if process.isRunning { process.terminate() }
    }
    process.waitUntilExit()
    return process.terminationReason == .exit && process.terminationStatus == 0
}

/// Keeps face_server.py running with the models loaded, so a check only has to open the camera.
final class FaceServer {
    private var process: Process?
    private var input: FileHandle?
    private var buffer = Data()
    private var replies: [String] = []
    private var ready = false
    private var nextID = 0
    private let cond = NSCondition()

    func start() {
        let process = Process()
        process.executableURL = project.appendingPathComponent(".venv/bin/python")
        process.arguments = ["-I", project.appendingPathComponent("face_unlock/face_server.py").path]
        let toServer = Pipe(), fromServer = Pipe()
        process.standardInput = toServer
        process.standardOutput = fromServer
        let errLog = home.appendingPathComponent("Library/Logs/FaceIDUnlockServer.log")
        if !FileManager.default.fileExists(atPath: errLog.path) {
            FileManager.default.createFile(atPath: errLog.path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: errLog) {
            handle.seekToEndOfFile()
            process.standardError = handle
        }
        fromServer.fileHandleForReading.readabilityHandler = { [weak self] h in self?.received(h.availableData) }
        process.terminationHandler = { [weak self] _ in
            guard let self else { return }
            self.cond.lock()
            self.ready = false
            self.cond.unlock()
            log("Face service stopped; restarting in 30 s")
            DispatchQueue.main.asyncAfter(deadline: .now() + 30) { self.start() }
        }
        do {
            try process.run()
            self.process = process
            input = toServer.fileHandleForWriting
        } catch {
            log("could not start face service: \(error)")
        }
    }

    private func received(_ data: Data) {
        cond.lock()
        buffer.append(data)
        while let newline = buffer.firstIndex(of: 0x0A) {
            let line = String(decoding: buffer[buffer.startIndex..<newline], as: UTF8.self)
            buffer.removeSubrange(buffer.startIndex...newline)
            if line == "ready" {
                ready = true
                log("Face service ready")
            } else {
                replies.append(line)
            }
        }
        cond.broadcast()
        cond.unlock()
    }

    /// Stops a running check (its faceMatches call then returns false).
    func cancel() {
        input?.write(Data("cancel\n".utf8))
    }

    /// true/false for match/no match; nil if the service isn't ready (caller falls back).
    func faceMatches(timeout: Double) -> Bool? {
        cond.lock()
        guard ready, let input else { cond.unlock(); return nil }
        nextID += 1
        let id = String(nextID)
        replies.removeAll()
        cond.unlock()

        input.write(Data("check \(id)\n".utf8))

        let deadline = Date().addingTimeInterval(timeout + 3)
        cond.lock()
        defer { cond.unlock() }
        while Date() < deadline {
            if let reply = replies.first(where: { $0.hasPrefix(id + " ") }) {
                return reply.hasSuffix(" match")
            }
            cond.wait(until: deadline)
        }
        return false
    }
}

// MARK: Status and logging

func log(_ message: String) {
    let line = "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
    if let handle = try? FileHandle(forWritingTo: logURL) {
        handle.seekToEndOfFile()
        handle.write(Data(line.utf8))
        try? handle.close()
    } else {
        try? line.write(to: logURL, atomically: true, encoding: .utf8)
    }
}

var lastResult = "Helper started"
var lastResultTime = Date()

/// Records a result (or, with nil, just refreshes the permission fields) for the app to show.
func writeStatus(_ result: String?) {
    if let result {
        log(result)
        lastResult = result
        lastResultTime = Date()
    }
    let status: [String: Any] = [
        "time": ISO8601DateFormatter().string(from: lastResultTime),
        "result": lastResult,
        "accessibility": AXIsProcessTrusted(),
        "camera": AVCaptureDevice.authorizationStatus(for: .video) == .authorized,
        "password_saved": passwordSaved(),
    ]
    try? FileManager.default.createDirectory(at: statusURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    if let data = try? JSONSerialization.data(withJSONObject: status, options: [.prettyPrinted]) {
        try? data.write(to: statusURL)
    }
}

// MARK: Agent

final class Agent {
    private let queue = DispatchQueue(label: "unlock")
    private var busy = false
    private var lastAttempt = Date.distantPast
    private var wakeTime = Date()
    /// Set after a typed password did not unlock the Mac; cleared when the agent restarts
    /// (the app restarts it after saving a new password). Prevents repeated wrong attempts.
    private var suspended = false
    private let faceServer = FaceServer()

    func start() {
        faceServer.start()
        // Ask for every permission now, while the screen is unlocked and prompts can be answered.
        // Reading the project triggers macOS's "access files in your Documents folder" prompt.
        _ = try? Data(contentsOf: configURL)
        _ = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
        AVCaptureDevice.requestAccess(for: .video) { _ in writeStatus("Helper started") }
        // Keep the app's view of the permissions current after the user grants them.
        Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { _ in writeStatus(nil) }

        let center = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.screensDidWakeNotification, NSWorkspace.didWakeNotification] {
            center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in self?.onWake() }
        }
    }

    private func onWake() {
        // Both wake notifications fire on lid open; handle once.
        guard !busy, Date().timeIntervalSince(lastAttempt) > 15 else { return }
        busy = true
        lastAttempt = Date()
        wakeTime = Date()
        queue.async {
            self.attempt()
            DispatchQueue.main.async { self.busy = false }
        }
    }

    private func attempt() {
        let config = Config.load()
        guard config.enabled else { return }
        guard !suspended else { return writeStatus("Paused: the saved password did not unlock the Mac. Save it again.") }
        guard AXIsProcessTrusted() else { return writeStatus("Needs Accessibility permission") }
        guard let password = loadPassword() else { return writeStatus("No password saved") }

        // Start the camera straight away: turning it on is the slowest step. If the Mac turns
        // out not to be locked, the check is cancelled and the camera switches off.
        var matched = false
        let faceDone = DispatchGroup()
        faceDone.enter()
        DispatchQueue.global(qos: .userInteractive).async {
            matched = self.faceServer.faceMatches(timeout: config.timeout) ?? faceMatches(timeout: config.timeout)
            faceDone.leave()
        }

        // With "require password after N seconds", macOS may only lock a moment after waking.
        var waited = 0.0
        while !screenIsLocked() && waited < 10 {
            Thread.sleep(forTimeInterval: 0.05)
            waited += 0.05
        }
        guard screenIsLocked() else {
            faceServer.cancel()
            faceDone.wait()
            return writeStatus("Woke up unlocked - nothing to do")
        }

        // Get the lock screen ready while the camera is still checking.
        // Your own typing always wins: if you touched the keyboard or trackpad after the lid
        // opened (a short grace period covers a key press used to wake the screen), stay out
        // of the way so the helper never mixes its keys with yours.
        let typedBeforeShift = userInputSince(wakeTime.addingTimeInterval(1.5))
        let shiftPressed = typedBeforeShift ? nil : lockScreenReady(settle: 0.3)
        if shiftPressed == nil { faceServer.cancel() }
        faceDone.wait()

        guard !typedBeforeShift else { return writeStatus("You started typing - left the password to you") }
        guard let shiftPressed else { return writeStatus("Display was not ready - left the password to you") }
        guard matched else { return writeStatus("Face not recognised") }
        guard !userInputSince(shiftPressed.addingTimeInterval(0.2)) else {
            return writeStatus("You started typing - left the password to you")
        }
        guard typeIntoLockScreen(password) else { return writeStatus("Screen unlocked by someone else first") }
        let typedAt = Date()
        let seconds = String(format: "%.1f", Date().timeIntervalSince(wakeTime))
        if waitForUnlock(within: 1.5) {
            return writeStatus("Unlocked with your face in \(seconds) s")
        }

        // Keys sent just as the screen wakes can be dropped. Try once more, more slowly,
        // before pausing - unless you have started typing yourself.
        guard screenIsLocked(), !userInputSince(typedAt.addingTimeInterval(0.2)) else {
            return writeStatus("You started typing - left the password to you")
        }
        clearPasswordBox()
        guard let again = lockScreenReady(settle: 1.0), !userInputSince(again.addingTimeInterval(0.2)),
              typeIntoLockScreen(password) else {
            return writeStatus("You started typing - left the password to you")
        }
        if waitForUnlock(within: 3) {
            writeStatus("Unlocked with your face in \(String(format: "%.1f", Date().timeIntervalSince(wakeTime))) s (second try)")
        } else {
            suspended = true
            writeStatus("Typed the password but the Mac stayed locked - paused")
        }
    }
}

// MARK: Entry point

let command = CommandLine.arguments.dropFirst().first ?? "run"
switch command {
case "run":
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    let agent = Agent()
    agent.start()
    app.run()
case "set-password":
    guard let password = readLine(strippingNewline: true), !password.isEmpty else {
        print("No password given"); exit(2)
    }
    guard isCorrectPassword(password) else { print("That is not the password for \(account)."); exit(3) }
    guard savePassword(password) else { print("Could not save to the Keychain."); exit(4) }
    print("Password verified and saved to your Keychain.")
case "clear-password":
    SecItemDelete(keychainQuery as CFDictionary)
    print("Password removed from your Keychain.")
case "status":
    print("{\"password_saved\": \(passwordSaved())}")
default:
    print("Usage: helper [run | set-password | clear-password | status]")
    exit(1)
}
