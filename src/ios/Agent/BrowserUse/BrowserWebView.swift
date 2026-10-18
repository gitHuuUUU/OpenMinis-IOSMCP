import SwiftUI
import WebKit

struct BrowserWebView: UIViewRepresentable {
    @ObservedObject var manager: BrowserUseManager
    func makeCoordinator() -> BrowserUseManager { manager }
    func makeUIView(context: Context) -> UIView { UIView() }
    static func dismantleUIView(_ container: UIView, coordinator: BrowserUseManager) {
        guard coordinator.webView.superview === container else { return }
        coordinator.webView.removeFromSuperview()
        coordinator.webView.translatesAutoresizingMaskIntoConstraints = true
        coordinator.restoreViewportFrame()
    }
    func updateUIView(_ container: UIView, context: Context) {
        let webView = manager.webView
        guard webView.superview !== container else { return }
        container.subviews.forEach { $0.removeFromSuperview() }
        webView.removeFromSuperview()
        webView.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            webView.topAnchor.constraint(equalTo: container.topAnchor),
            webView.bottomAnchor.constraint(equalTo: container.bottomAnchor)
        ])
    }
}
