// Face scan indicator at the top middle of the screen, in Liquid Glass: a capsule grows out
// of the notch, shows an animated face while scanning, then a check mark or a shake.
//
// Runs as its own small app (no permissions needed), started by the lock-screen helper.
// Everything drives it with Darwin notifications:
//   local.faceidunlock.overlay.scan | .success | .fail | .hide
//   local.faceidunlock.overlay.unlocked   the helper unlocked the Mac: play scan -> check
//                                         once the lock screen has really gone
import AppKit
import QuartzCore
import notify

// MARK: Face glyph

/// The animated face: corner brackets with a rotating rainbow shimmer, eyes, nose, mouth,
/// a sweeping scan beam, and a ring + check mark for success.
final class FaceGlyphView: NSView {
    private let side: CGFloat = 96
    private let shimmerHost = CALayer()
    private let shimmer = CAGradientLayer()
    private let brackets = CAShapeLayer()
    private let features = CAShapeLayer()
    private let mouth = CAShapeLayer()
    private let beam = CAGradientLayer()
    private let ring = CAShapeLayer()
    private let check = CAShapeLayer()

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.masksToBounds = false
        build()
    }

    required init?(coder: NSCoder) { fatalError() }

    private var box: CGRect {
        CGRect(x: (bounds.width - side) / 2, y: (bounds.height - side) / 2, width: side, height: side)
    }

    private func bracketPath() -> CGPath {
        let b = box, arm: CGFloat = 24, r: CGFloat = 10
        let p = CGMutablePath()
        // Each corner: arm along one edge, rounded corner, arm along the other.
        for (x, y, dx, dy) in [(b.minX, b.maxY, 1.0, -1.0), (b.maxX, b.maxY, -1.0, -1.0),
                               (b.minX, b.minY, 1.0, 1.0), (b.maxX, b.minY, -1.0, 1.0)] {
            p.move(to: CGPoint(x: x, y: y + dy * arm))
            p.addLine(to: CGPoint(x: x, y: y + dy * r))
            p.addQuadCurve(to: CGPoint(x: x + dx * r, y: y), control: CGPoint(x: x, y: y))
            p.addLine(to: CGPoint(x: x + dx * arm, y: y))
        }
        return p
    }

    private func featurePath() -> CGPath {
        let c = CGPoint(x: box.midX, y: box.midY)
        let p = CGMutablePath()
        for dx: CGFloat in [-17, 17] {  // eyes
            p.move(to: CGPoint(x: c.x + dx, y: c.y + 18))
            p.addLine(to: CGPoint(x: c.x + dx, y: c.y + 8))
        }
        p.move(to: CGPoint(x: c.x + 1, y: c.y + 14))  // nose
        p.addLine(to: CGPoint(x: c.x + 1, y: c.y - 2))
        p.addLine(to: CGPoint(x: c.x - 5, y: c.y - 2))
        return p
    }

    private func mouthPath(smile: Bool) -> CGPath {
        let c = CGPoint(x: box.midX, y: box.midY)
        let p = CGMutablePath()
        p.move(to: CGPoint(x: c.x - 16, y: c.y - 14))
        p.addQuadCurve(to: CGPoint(x: c.x + 16, y: c.y - 14),
                       control: CGPoint(x: c.x, y: smile ? c.y - 26 : c.y - 4))
        return p
    }

    private func stroke(_ layer: CAShapeLayer, width: CGFloat, color: NSColor) {
        layer.fillColor = nil
        layer.strokeColor = color.cgColor
        layer.lineWidth = width
        layer.lineCap = .round
        layer.lineJoin = .round
        layer.frame = bounds
    }

    private func build() {
        guard let root = layer else { return }
        let white = NSColor.white

        // Brackets: a rainbow conic gradient seen through a bracket-shaped mask. The gradient
        // rotates underneath the fixed mask, so the colours travel around the frame.
        shimmerHost.frame = bounds
        let diagonal = side * 1.6
        shimmer.type = .conic
        shimmer.colors = ["#35e8ff", "#5b7cff", "#b35bff", "#ff5fd2", "#ffb86b", "#35e8ff"]
            .map { NSColor(hex: $0).cgColor }
        shimmer.startPoint = CGPoint(x: 0.5, y: 0.5)
        shimmer.endPoint = CGPoint(x: 1, y: 0.5)
        shimmer.bounds = CGRect(x: 0, y: 0, width: diagonal, height: diagonal)
        shimmer.position = CGPoint(x: bounds.midX, y: bounds.midY)
        shimmerHost.addSublayer(shimmer)
        let mask = CAShapeLayer()
        stroke(mask, width: 5, color: .white)
        mask.path = bracketPath()
        shimmerHost.mask = mask
        root.addSublayer(shimmerHost)

        stroke(brackets, width: 5, color: white.withAlphaComponent(0.35))
        brackets.path = bracketPath()
        root.addSublayer(brackets)

        stroke(features, width: 5, color: white)
        features.path = featurePath()
        root.addSublayer(features)
        stroke(mouth, width: 5, color: white)
        mouth.path = mouthPath(smile: true)
        root.addSublayer(mouth)

        beam.colors = [NSColor.clear, NSColor(hex: "#baffff"), NSColor.clear].map(\.cgColor)
        beam.startPoint = CGPoint(x: 0, y: 0.5)
        beam.endPoint = CGPoint(x: 1, y: 0.5)
        beam.bounds = CGRect(x: 0, y: 0, width: side + 16, height: 3)
        beam.position = CGPoint(x: box.midX, y: box.maxY)
        beam.shadowColor = NSColor(hex: "#35e8ff").cgColor
        beam.shadowRadius = 8
        beam.shadowOpacity = 1
        beam.shadowOffset = .zero
        root.addSublayer(beam)

        let ringRect = box.insetBy(dx: 6, dy: 6)
        stroke(ring, width: 6, color: NSColor(hex: "#34e89e"))
        ring.path = CGPath(ellipseIn: ringRect, transform: nil)
        ring.strokeEnd = 0
        ring.shadowColor = NSColor(hex: "#34e89e").cgColor
        ring.shadowRadius = 10
        ring.shadowOpacity = 0.9
        ring.shadowOffset = .zero
        root.addSublayer(ring)

        stroke(check, width: 8, color: NSColor(hex: "#34e89e"))
        let c = CGPoint(x: box.midX, y: box.midY)
        let tick = CGMutablePath()
        tick.move(to: CGPoint(x: c.x - 22, y: c.y + 1))
        tick.addLine(to: CGPoint(x: c.x - 6, y: c.y - 15))
        tick.addLine(to: CGPoint(x: c.x + 24, y: c.y + 17))
        check.path = tick
        check.strokeEnd = 0
        root.addSublayer(check)
    }

    func startScanning() {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        for layer in [shimmerHost, brackets, features, mouth, beam] as [CALayer] { layer.opacity = 1 }
        ring.strokeEnd = 0
        check.strokeEnd = 0
        features.strokeColor = NSColor.white.cgColor
        mouth.strokeColor = NSColor.white.cgColor
        mouth.path = mouthPath(smile: true)
        CATransaction.commit()

        let spin = CABasicAnimation(keyPath: "transform.rotation.z")
        spin.fromValue = 0
        spin.toValue = -Double.pi * 2
        spin.duration = 2.2
        spin.repeatCount = .infinity
        shimmer.add(spin, forKey: "spin")

        let sweep = CABasicAnimation(keyPath: "position.y")
        sweep.fromValue = box.maxY - 4
        sweep.toValue = box.minY + 4
        sweep.duration = 0.9
        sweep.autoreverses = true
        sweep.repeatCount = .infinity
        sweep.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        beam.add(sweep, forKey: "sweep")

        let breathe = CABasicAnimation(keyPath: "opacity")
        breathe.fromValue = 1
        breathe.toValue = 0.55
        breathe.duration = 0.7
        breathe.autoreverses = true
        breathe.repeatCount = .infinity
        features.add(breathe, forKey: "breathe")
    }

    func showSuccess() {
        beam.removeAllAnimations()
        features.removeAllAnimations()
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.18)
        for layer in [shimmerHost, brackets, features, mouth, beam] as [CALayer] { layer.opacity = 0 }
        CATransaction.commit()

        draw(ring, duration: 0.32, delay: 0.05)
        draw(check, duration: 0.26, delay: 0.3)

        let pop = CAKeyframeAnimation(keyPath: "transform.scale")
        pop.values = [0.9, 1.08, 1.0]
        pop.keyTimes = [0, 0.6, 1]
        pop.duration = 0.45
        layer?.add(pop, forKey: "pop")
    }

    func showFailure() {
        beam.removeAllAnimations()
        features.removeAllAnimations()
        shimmer.removeAllAnimations()
        let red = NSColor(hex: "#ff5a6e").cgColor
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.25)
        beam.opacity = 0
        shimmerHost.opacity = 0
        brackets.strokeColor = red
        brackets.opacity = 1
        features.strokeColor = red
        features.opacity = 1
        mouth.strokeColor = red
        mouth.path = mouthPath(smile: false)
        CATransaction.commit()
    }

    func resetBrackets() {
        brackets.strokeColor = NSColor.white.withAlphaComponent(0.35).cgColor
    }

    private func draw(_ layer: CAShapeLayer, duration: Double, delay: Double) {
        let a = CABasicAnimation(keyPath: "strokeEnd")
        a.fromValue = 0
        a.toValue = 1
        a.duration = duration
        a.beginTime = CACurrentMediaTime() + delay
        a.fillMode = .backwards
        a.timingFunction = CAMediaTimingFunction(name: .easeOut)
        layer.strokeEnd = 1
        layer.add(a, forKey: "draw")
    }
}

// MARK: Overlay window

final class FaceOverlay {
    private var window: NSPanel?
    private var glass: NSView?
    private var glyph: FaceGlyphView?
    private var label: NSTextField?
    private var pending: DispatchWorkItem?
    /// Bumped on every show, so a finishing collapse never hides a newer animation.
    private var generation = 0
    private var celebrateUntil = Date.distantPast
    private var lastUnlockSignal = Date.distantPast
    private let windowSize = NSSize(width: 360, height: 260)
    private let panelSize = NSSize(width: 210, height: 196)

    private var firstName: String {
        NSFullUserName().split(separator: " ").first.map(String.init) ?? ""
    }

    // MARK: Public states

    func scanning(_ text: String = "Looking for you…") {
        prepare()
        glyph?.resetBrackets()
        glyph?.startScanning()
        setLabel(text, color: .white)
        setTint(NSColor.black.withAlphaComponent(0.35))
        expand()
        schedule(after: 15) { [weak self] in self?.collapse() }  // never linger if nobody updates it
    }

    func success() {
        guard window?.isVisible == true else { return }
        window?.orderFrontRegardless()
        glyph?.showSuccess()
        setLabel(firstName.isEmpty ? "Welcome back" : "Welcome back, \(firstName)", color: .white)
        setTint(NSColor(hex: "#0f5a3c").withAlphaComponent(0.45))
        schedule(after: 1.3) { [weak self] in self?.collapse() }
    }

    func failure(_ text: String = "Not recognised") {
        guard window?.isVisible == true else { return }
        window?.orderFrontRegardless()
        glyph?.showFailure()
        setLabel(text, color: NSColor(hex: "#ffc2ca"))
        setTint(NSColor(hex: "#5a0f1c").withAlphaComponent(0.45))
        shake()
        schedule(after: 1.5) { [weak self] in self?.collapse() }
    }

    /// For the lock screen, where nothing can be drawn: plays the whole moment - a brief scan
    /// turning into the check mark - once the desktop is really back. Waits for macOS's own
    /// "screen is unlocked" signal (whichever arrives first), then for the display and the
    /// fade-in, because a window shown while the lock screen is still fading out is not drawn.
    func unlocked() {
        overlayLog("unlock animation requested")
        celebrateUntil = Date().addingTimeInterval(6)
        if Date().timeIntervalSince(lastUnlockSignal) < 3 {
            celebrate(reason: "signal came first")
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                self?.celebrate(reason: "no unlock signal after 3 s")
            }
        }
    }

    private func screenUnlockedSignal() {
        lastUnlockSignal = Date()
        celebrate(reason: "unlock signal")
    }

    private func celebrate(reason: String) {
        guard Date() < celebrateUntil else { return }
        celebrateUntil = .distantPast
        var waited = 0.0
        func attempt() {
            let ready = !sessionLocked() && CGDisplayIsAsleep(CGMainDisplayID()) == 0
            if !ready && waited < 4 {
                waited += 0.1
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1, execute: attempt)
                return
            }
            // Let the desktop finish fading in before drawing on it.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                guard let self else { return }
                self.scanning()
                self.reportVisibility(after: 0.4, what: "shown (\(reason), waited \(String(format: "%.1f", waited)) s)")
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.75) { self.success() }
            }
        }
        attempt()
    }

    /// Logs whether macOS actually put the window on screen, to diagnose missed animations.
    private func reportVisibility(after delay: Double, what: String) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let window = self?.window else { return }
            let drawn = window.occlusionState.contains(.visible)
            overlayLog("\(what): \(drawn ? "visible on screen" : "NOT visible (hidden by macOS)")")
            if !drawn { window.orderFrontRegardless() }
        }
    }

    func hide() {
        guard window?.isVisible == true else { return }
        collapse()
    }

    // MARK: Building

    private var screen: NSScreen? { NSScreen.screens.first }

    /// The notch rectangle in window coordinates, or a notch-sized pill at the top edge.
    private var notchFrame: NSRect {
        var width: CGFloat = 180
        if let s = screen, s.safeAreaInsets.top > 0,
           let left = s.auxiliaryTopLeftArea, let right = s.auxiliaryTopRightArea {
            width = s.frame.width - left.width - right.width
        }
        let height = max(screen?.safeAreaInsets.top ?? 0, 32)
        return NSRect(x: (windowSize.width - width) / 2, y: windowSize.height - height, width: width, height: height)
    }

    private var expandedFrame: NSRect {
        NSRect(x: (windowSize.width - panelSize.width) / 2, y: windowSize.height - panelSize.height,
               width: panelSize.width, height: panelSize.height)
    }

    private func prepare() {
        pending?.cancel()
        generation += 1
        if window == nil { build() }
        guard let window, let screen else { return }
        window.setFrame(NSRect(x: screen.frame.midX - windowSize.width / 2,
                               y: screen.frame.maxY - windowSize.height,
                               width: windowSize.width, height: windowSize.height), display: false)
        if !window.isVisible {
            glass?.frame = notchFrame
            setCorner(notchFrame.height / 2)
            glass?.alphaValue = 0
        }
        // Always re-assert: after sleep or the lock screen, macOS can report the window as
        // visible while no longer drawing it.
        window.orderFrontRegardless()
    }

    private func build() {
        let panel = NSPanel(contentRect: NSRect(origin: .zero, size: windowSize),
                            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.hidesOnDeactivate = false
        // Above all apps, full-screen apps and the menu bar. (macOS never shows app windows on
        // the lock screen, and a level above it only interferes with the unlock transition.)
        panel.level = .screenSaver
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenAuxiliary]

        let root = NSView(frame: NSRect(origin: .zero, size: windowSize))
        root.wantsLayer = true

        let content = NSView(frame: NSRect(origin: .zero, size: panelSize))
        let face = FaceGlyphView(frame: NSRect(x: (panelSize.width - 130) / 2, y: 44, width: 130, height: 130))
        let text = NSTextField(labelWithString: "")
        text.font = .systemFont(ofSize: 14, weight: .semibold)
        text.alignment = .center
        text.frame = NSRect(x: 8, y: 16, width: panelSize.width - 16, height: 20)
        content.addSubview(face)
        content.addSubview(text)
        content.autoresizingMask = [.minXMargin, .maxXMargin, .minYMargin]

        let glassView: NSView
        if #available(macOS 26.0, *) {
            let g = NSGlassEffectView(frame: notchFrame)
            g.style = .regular
            g.contentView = content
            glassView = g
        } else {
            let v = NSVisualEffectView(frame: notchFrame)
            v.material = .hudWindow
            v.state = .active
            v.blendingMode = .behindWindow
            v.wantsLayer = true
            v.layer?.masksToBounds = true
            v.addSubview(content)
            glassView = v
        }
        root.addSubview(glassView)
        panel.contentView = root

        window = panel
        glass = glassView
        glyph = face
        label = text
    }

    // MARK: Animation

    private func expand() {
        guard let glass else { return }
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.5
            ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.2, 1.3, 0.35, 1)  // springy overshoot
            glass.animator().frame = expandedFrame
            glass.animator().alphaValue = 1
        }
        setCorner(46)
        contentFade(to: 1, duration: 0.35, delay: 0.12)
    }

    private func collapse() {
        pending?.cancel()
        guard let glass, let window else { return }
        let shownAs = generation
        contentFade(to: 0, duration: 0.15, delay: 0)
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.38
            ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.5, 0, 0.2, 1)
            glass.animator().frame = notchFrame
            glass.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            if self?.generation == shownAs { window.orderOut(nil) }
        })
        setCorner(notchFrame.height / 2)
    }

    private func contentFade(to value: CGFloat, duration: Double, delay: Double) {
        let views = [glyph, label].compactMap { $0 }
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = duration
                views.forEach { $0.animator().alphaValue = value }
            }
        }
    }

    private func shake() {
        guard let layer = glass?.layer else { return }
        let a = CAKeyframeAnimation(keyPath: "transform.translation.x")
        a.values = [0, -14, 12, -9, 6, -3, 0]
        a.duration = 0.5
        layer.add(a, forKey: "shake")
    }

    private func setCorner(_ radius: CGFloat) {
        if #available(macOS 26.0, *), let g = glass as? NSGlassEffectView {
            g.cornerRadius = radius
        } else {
            glass?.layer?.cornerRadius = radius
        }
    }

    private func setTint(_ color: NSColor) {
        if #available(macOS 26.0, *), let g = glass as? NSGlassEffectView {
            g.tintColor = color
        }
    }

    private func setLabel(_ text: String, color: NSColor) {
        label?.stringValue = text
        label?.textColor = color
    }

    private func schedule(after seconds: Double, _ work: @escaping () -> Void) {
        pending?.cancel()
        let item = DispatchWorkItem(block: work)
        pending = item
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: item)
    }

    /// Lets the helper, sudo and Face Vault drive the overlay.
    func listenForNotifications() {
        let states: [(String, () -> Void)] = [
            ("scan", { [weak self] in self?.scanning() }),
            ("success", { [weak self] in self?.success() }),
            ("fail", { [weak self] in self?.failure() }),
            ("hide", { [weak self] in self?.hide() }),
            ("unlocked", { [weak self] in self?.unlocked() }),
        ]
        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.apple.screenIsUnlocked"), object: nil, queue: .main
        ) { [weak self] _ in self?.screenUnlockedSignal() }
        for (name, action) in states {
            var token: Int32 = 0
            notify_register_dispatch("local.faceidunlock.overlay.\(name)", &token, .main) { _ in action() }
        }
    }
}

func sessionLocked() -> Bool {
    guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
    return (session["CGSSessionScreenIsLocked"] as? Bool) ?? false
}

func overlayLog(_ message: String) {
    let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/FaceIDUnlockOverlay.log")
    let line = "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
    if let handle = try? FileHandle(forWritingTo: url) {
        handle.seekToEndOfFile()
        handle.write(Data(line.utf8))
        try? handle.close()
    } else {
        try? line.write(to: url, atomically: true, encoding: .utf8)
    }
}

extension NSColor {
    convenience init(hex: String) {
        var value: UInt64 = 0
        Scanner(string: hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))).scanHexInt64(&value)
        self.init(srgbRed: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255,
                  blue: CGFloat(value & 0xFF) / 255, alpha: 1)
    }
}
