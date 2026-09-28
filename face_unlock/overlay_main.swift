// Entry point for "Face ID Unlock Overlay.app": shows the Liquid Glass scan animation when
// asked to over Darwin notifications (see overlay.swift).
//
//   FaceIDUnlockOverlay          run (started and kept alive by the lock-screen helper)
//   FaceIDUnlockOverlay demo     preview: unlock moment, then a live scan that fails
import AppKit

@main
enum OverlayMain {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)  // no Dock icon
        let overlay = FaceOverlay()
        if CommandLine.arguments.dropFirst().first == "demo" {
            let steps: [(Double, (FaceOverlay) -> Void)] = [
                (0.3, { $0.unlocked() }),
                (6.0, { $0.scanning() }), (8.5, { $0.failure() }), (11.0, { _ in exit(0) }),
            ]
            for (at, step) in steps {
                DispatchQueue.main.asyncAfter(deadline: .now() + at) { step(overlay) }
            }
        } else {
            overlay.listenForNotifications()
            overlayLog("Overlay started")
        }
        app.run()
    }
}
