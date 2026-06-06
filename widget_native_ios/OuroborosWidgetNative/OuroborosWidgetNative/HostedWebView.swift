import SwiftUI
import WebKit

#if os(iOS)
import UIKit
typealias NativeViewRepresentable = UIViewRepresentable
typealias NativeColor = UIColor
#else
import AppKit
typealias NativeViewRepresentable = NSViewRepresentable
typealias NativeColor = NSColor
#endif

struct HostedWebView: NativeViewRepresentable {
    let url: URL
    let reloadID: UUID
    @Binding var loadState: HostedWebLoadState

    func makeCoordinator() -> Coordinator {
        Coordinator(loadState: $loadState)
    }

#if os(iOS)
    func makeUIView(context: Context) -> WKWebView {
        buildWebView(context: context)
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        reloadIfNeeded(webView, context: context)
    }
#else
    func makeNSView(context: Context) -> WKWebView {
        buildWebView(context: context)
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        reloadIfNeeded(webView, context: context)
    }
#endif

    private func buildWebView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.websiteDataStore = .nonPersistent()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.backgroundColor = NativeColor.systemGroupedBackground
        webView.isOpaque = false
        webView.backgroundColor = NativeColor.systemGroupedBackground
        load(url: url, into: webView)
        context.coordinator.lastURL = url
        context.coordinator.lastReloadID = reloadID
        return webView
    }

    private func reloadIfNeeded(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastURL != url || context.coordinator.lastReloadID != reloadID {
            load(url: url, into: webView)
            context.coordinator.lastURL = url
            context.coordinator.lastReloadID = reloadID
        }
    }

    private func load(url: URL, into webView: WKWebView) {
        let targetURL = cacheBustedURL(url)
        loadState = .loading(targetURL.absoluteString)
        let request = URLRequest(url: targetURL, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: 30)
        webView.load(request)
    }

    private func cacheBustedURL(_ url: URL) -> URL {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return url }
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "native" || $0.name == "v" }
        items.append(URLQueryItem(name: "native", value: "1"))
        items.append(URLQueryItem(name: "v", value: reloadID.uuidString))
        components.queryItems = items
        return components.url ?? url
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var lastURL: URL?
        var lastReloadID: UUID?
        private var loadState: Binding<HostedWebLoadState>

        init(loadState: Binding<HostedWebLoadState>) {
            self.loadState = loadState
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            loadState.wrappedValue = .loading(webView.url?.absoluteString ?? "")
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            loadState.wrappedValue = .loaded(webView.url?.absoluteString ?? "")
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            loadState.wrappedValue = .failed(message: error.localizedDescription)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            loadState.wrappedValue = .failed(message: error.localizedDescription)
        }
    }
}

enum HostedWebLoadState: Equatable {
    case idle
    case loading(String)
    case loaded(String)
    case failed(message: String)
}
