import SwiftUI
import UserNotifications
import LocalAuthentication
import WidgetKit
import ActivityKit

private enum WidgetNativeTab: String, CaseIterable, Hashable {
    case command
    case overview
    case reflection
    case trades
    case dashboard
    case settings

    var title: String {
        switch self {
        case .command: return "Command"
        case .overview: return "Overview"
        case .reflection: return "Reflection"
        case .trades: return "Trades"
        case .dashboard: return "Dashboard"
        case .settings: return "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .command: return "shield.lefthalf.filled"
        case .overview: return "house"
        case .reflection: return "sparkles.rectangle.stack"
        case .trades: return "list.bullet.rectangle"
        case .dashboard: return "chart.xyaxis.line"
        case .settings: return "gearshape"
        }
    }
}

private struct WidgetNativeConfig {
    var hostInput: String
    var token: String

    var normalizedOrigin: String {
        let raw = hostInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return "" }
        let prefixed = raw.contains("://") ? raw : "http://\(raw)"
        guard let components = URLComponents(string: prefixed),
              let scheme = components.scheme,
              let host = components.host else {
            return ""
        }
        return "\(scheme)://\(host)"
    }

    var hasToken: Bool {
        !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var isReady: Bool {
        !normalizedOrigin.isEmpty && hasToken
    }

    var redactedTokenPreview: String {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "未設定" }
        if trimmed.count <= 8 { return "設定済み" }
        return "\(trimmed.prefix(4))••••\(trimmed.suffix(2))"
    }

    private var encodedToken: String {
        token.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
    }

    func url(for tab: WidgetNativeTab) -> URL? {
        switch tab {
        case .command:
            guard isReady else { return nil }
            return statusURL
        case .overview:
            guard isReady else { return nil }
            return URL(string: "\(normalizedOrigin):8787/widget-react/index.html?token=\(encodedToken)&scene=overview&native=1")
        case .reflection:
            guard isReady else { return nil }
            return URL(string: "\(normalizedOrigin):8787/widget-react/index.html?token=\(encodedToken)&scene=reflection&native=1")
        case .trades:
            guard isReady else { return nil }
            return URL(string: "\(normalizedOrigin):8787/widget-react/index.html?token=\(encodedToken)&scene=history&native=1")
        case .dashboard:
            return dashboardURL
        case .settings:
            return nil
        }
    }

    var statusURL: URL? {
        guard isReady else { return nil }
        return URL(string: "\(normalizedOrigin):8787/widget-status.json?token=\(encodedToken)")
    }

    var dashboardURL: URL? {
        guard !normalizedOrigin.isEmpty else { return nil }
        return URL(string: "\(normalizedOrigin):8793/tools/unified_dashboard.html")
    }

    func redactedURLString(for tab: WidgetNativeTab) -> String {
        guard let url = url(for: tab) else { return "未設定" }
        guard tab != .dashboard else { return url.absoluteString }
        let queryItems = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let sceneSuffix = queryItems.first(where: { $0.name == "scene" })?.value.map { "&scene=\($0)" } ?? ""
        let nativeSuffix = queryItems.first(where: { $0.name == "native" })?.value.map { "&native=\($0)" } ?? ""
        return "\(normalizedOrigin):8787\(url.path)?token=\(redactedTokenPreview)\(sceneSuffix)\(nativeSuffix)"
    }

    var helperLines: [String] {
        [
            "1. iPhone と VM を同じ Tailscale に参加させます",
            "2. Host には例として 100.66.216.5 のような Tailscale IP を入れます",
            "3. Token には widget 用 token を入れます",
            "4. Overview / Reflection はネイティブ埋め込み表示で開きます",
            "5. Lock / StandBy はURL指定用として裏側に残します",
            "6. Dashboard は /tools/unified_dashboard.html を開きます",
        ]
    }
}

struct RootTabView: View {
    @AppStorage(OuroborosWidgetSharedConfig.hostKey, store: OuroborosWidgetSharedConfig.defaults) private var hostInput: String = ""
    @AppStorage(OuroborosWidgetSharedConfig.tokenKey, store: OuroborosWidgetSharedConfig.defaults) private var token: String = ""
    @AppStorage("native_notifications_enabled", store: OuroborosWidgetSharedConfig.defaults) private var notificationsEnabled: Bool = false
    @AppStorage("ntfy_topic_url", store: OuroborosWidgetSharedConfig.defaults) private var ntfyTopicURL: String = ""
    @AppStorage("ntfy_bearer_token", store: OuroborosWidgetSharedConfig.defaults) private var ntfyBearerToken: String = ""
    @AppStorage("native_privacy_lock_enabled", store: OuroborosWidgetSharedConfig.defaults) private var privacyLockEnabled: Bool = false
    @State private var selectedTab: WidgetNativeTab = .overview

    private var config: WidgetNativeConfig {
        WidgetNativeConfig(hostInput: hostInput, token: token)
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack {
                NativeCommandCenterView(config: config, privacyLockEnabled: privacyLockEnabled)
            }
            .tabItem {
                Label(WidgetNativeTab.command.title, systemImage: WidgetNativeTab.command.systemImage)
            }
            .tag(WidgetNativeTab.command)

            hostedScreen(for: .overview)
                .tabItem {
                    Label(WidgetNativeTab.overview.title, systemImage: WidgetNativeTab.overview.systemImage)
                }
                .tag(WidgetNativeTab.overview)

            hostedScreen(for: .reflection)
                .tabItem {
                    Label(WidgetNativeTab.reflection.title, systemImage: WidgetNativeTab.reflection.systemImage)
                }
                .tag(WidgetNativeTab.reflection)

            hostedScreen(for: .trades)
                .tabItem {
                    Label(WidgetNativeTab.trades.title, systemImage: WidgetNativeTab.trades.systemImage)
                }
                .tag(WidgetNativeTab.trades)

            hostedScreen(for: .dashboard)
                .tabItem {
                    Label(WidgetNativeTab.dashboard.title, systemImage: WidgetNativeTab.dashboard.systemImage)
                }
                .tag(WidgetNativeTab.dashboard)

            NavigationStack {
                NativeSettingsView(
                    hostInput: $hostInput,
                    token: $token,
                    notificationsEnabled: $notificationsEnabled,
                    ntfyTopicURL: $ntfyTopicURL,
                    ntfyBearerToken: $ntfyBearerToken,
                    privacyLockEnabled: $privacyLockEnabled,
                    config: config
                )
            }
            .tabItem {
                Label(WidgetNativeTab.settings.title, systemImage: WidgetNativeTab.settings.systemImage)
            }
            .tag(WidgetNativeTab.settings)
        }
        .onAppear {
            migrateLegacyDefaultsIfNeeded()
        }
    }

    @ViewBuilder
    private func hostedScreen(for tab: WidgetNativeTab) -> some View {
        HostedRouteView(tab: tab, config: config)
    }

    private func migrateLegacyDefaultsIfNeeded() {
        let shared = OuroborosWidgetSharedConfig.defaults
        let standard = UserDefaults.standard
        if (shared.string(forKey: OuroborosWidgetSharedConfig.hostKey) ?? "").isEmpty,
           let legacyHost = standard.string(forKey: OuroborosWidgetSharedConfig.hostKey),
           !legacyHost.isEmpty {
            shared.set(legacyHost, forKey: OuroborosWidgetSharedConfig.hostKey)
        }
        if (shared.string(forKey: OuroborosWidgetSharedConfig.tokenKey) ?? "").isEmpty,
           let legacyToken = standard.string(forKey: OuroborosWidgetSharedConfig.tokenKey),
           !legacyToken.isEmpty {
            shared.set(legacyToken, forKey: OuroborosWidgetSharedConfig.tokenKey)
        }
    }
}

private struct HostedRouteView: View {
    let tab: WidgetNativeTab
    let config: WidgetNativeConfig
    @AppStorage("native_notifications_enabled", store: OuroborosWidgetSharedConfig.defaults) private var notificationsEnabled: Bool = false
    @AppStorage("native_notifications_last_failure_sent", store: OuroborosWidgetSharedConfig.defaults) private var lastFailureSent: Double = 0
    @State private var reloadID = UUID()
    @State private var loadState: HostedWebLoadState = .idle

    private var pageURL: URL? {
        config.url(for: tab)
    }

    var body: some View {
        Group {
            if let pageURL {
                ZStack(alignment: .topTrailing) {
                    HostedWebView(url: pageURL, reloadID: reloadID, loadState: $loadState)
                    webLoadOverlay
                    Button {
                        reloadID = UUID()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 17, weight: .bold))
                            .frame(width: 42, height: 42)
                            .background(.ultraThinMaterial, in: Circle())
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 10)
                    .padding(.trailing, 12)
                    .accessibilityLabel("Reload")
                }
            } else {
                NativeSetupRequiredView(config: config, tab: tab)
                    .padding(16)
            }
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .onChange(of: loadState) { _, newState in
            notifyIfNeeded(for: newState)
        }
    }

    @ViewBuilder
    private var webLoadOverlay: some View {
        switch loadState {
        case .idle:
            EmptyView()
        case .loading:
            VStack(spacing: 10) {
                ProgressView()
                Text("読み込み中...")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(uiColor: .systemGroupedBackground).opacity(0.86))
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        case .loaded:
            EmptyView()
        case .failed(let message):
            VStack(alignment: .leading, spacing: 10) {
                Label("Web表示を読み込めません", systemImage: "exclamationmark.triangle")
                    .font(.headline)
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(tab == .dashboard
                     ? "DashboardはHostだけで開きます。TailscaleがONか、Hostが http://100.66.216.5 になっているか確認してください。"
                     : "TailscaleがONか、Hostが http://100.66.216.5 になっているか、tokenが正しいか確認してください。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let pageURL {
                    Text(pageURL.absoluteString)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    Link("Safariで開いて確認", destination: pageURL)
                        .font(.caption.weight(.bold))
                }
                Button("再読み込み") {
                    reloadID = UUID()
                }
                .buttonStyle(.borderedProminent)
            }
            .padding(18)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Color(uiColor: .systemGroupedBackground).opacity(0.94))
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
    }

    private func notifyIfNeeded(for state: HostedWebLoadState) {
        guard notificationsEnabled else { return }
        guard case .failed(let message) = state else { return }
        let now = Date().timeIntervalSince1970
        guard now - lastFailureSent > 30 * 60 else { return }
        lastFailureSent = now
        Task {
            await OuroborosNativeNotifier.shared.send(
                title: "Ouroboros 接続確認",
                body: "\(tab.title) の表示に失敗: \(message)",
                interruptionLevel: .timeSensitive
            )
            NativeNotificationHistoryStore.append(level: "WARN", title: "Web表示失敗", body: "\(tab.title): \(message)")
        }
    }
}

private struct NativeStatusSnapshot: Decodable {
    struct Goal: Decodable {
        var pnl_jpy: Double?
        var goal_jpy: Double?
        var remaining_jpy: Double?
        var closed_n: Int?
    }

    struct Weekly: Decodable {
        var pnl_jpy_sum: Double?
        var win_rate_pct: Double?
        var closed_n: Int?
    }

    struct Drift: Decodable {
        var status: String?
        var remaining_samples: Int?
    }

    struct Balance: Decodable {
        var label: String?
        var value_jpy: Double?
        var available_jpy: Double?

        init(label: String? = nil, value_jpy: Double? = nil, available_jpy: Double? = nil) {
            self.label = label
            self.value_jpy = value_jpy
            self.available_jpy = available_jpy
        }

        enum CodingKeys: String, CodingKey {
            case label
            case value_jpy
            case available_jpy
            case jpy
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            label = try container.decodeIfPresent(String.self, forKey: .label)
            value_jpy = try container.decodeIfPresent(Double.self, forKey: .value_jpy)
                ?? container.decodeIfPresent(Double.self, forKey: .jpy)
            available_jpy = try container.decodeIfPresent(Double.self, forKey: .available_jpy)
        }
    }

    struct IBKRAccount: Decodable {
        var available: Bool?
        var stale: Bool?
        var account_id: String?
        var net_liquidation_jpy: Double?
        var available_funds_jpy: Double?
        var buying_power_jpy: Double?
        var total_cash_value_jpy: Double?
        var unrealized_pnl_jpy: Double?
        var age_hours: Double?
    }

    struct BitflyerAccount: Decodable {
        var available: Bool?
        var jpy: Double?
        var collateral_jpy: Double?
        var jpy_balance: Double?
        var available_collateral_jpy: Double?
        var label: String?
        var source: String?
        var error: String?
        var updated_at: String?
    }

    struct LatestTrade: Decodable {
        var time: String?
        var result: String?
        var pnl_jpy: Double?
    }

    var generated_at_jst: String?
    var state_updated_at: String?
    var effective_stage: String?
    var status_level: String?
    var trade_enabled: Bool?
    var runner_alive: Bool?
    var goal: Goal?
    var weekly: Weekly?
    var drift: Drift?
    var balance: Balance?
    var bitflyer_account: BitflyerAccount?
    var ibkr_account: IBKRAccount?
    var latest_trade: LatestTrade?
}

private struct NativeNotificationEvent: Codable, Identifiable {
    var id: String
    var dateText: String
    var level: String
    var title: String
    var body: String

    static func make(level: String, title: String, body: String) -> NativeNotificationEvent {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ja_JP")
        formatter.dateFormat = "MM/dd HH:mm"
        return NativeNotificationEvent(
            id: UUID().uuidString,
            dateText: formatter.string(from: Date()),
            level: level,
            title: title,
            body: body
        )
    }
}

private enum NativeNotificationHistoryStore {
    static let key = "native_notification_history_json"

    static func load() -> [NativeNotificationEvent] {
        guard let raw = OuroborosWidgetSharedConfig.defaults.string(forKey: key),
              let data = raw.data(using: .utf8),
              let items = try? JSONDecoder().decode([NativeNotificationEvent].self, from: data) else {
            return []
        }
        return items
    }

    static func append(level: String, title: String, body: String) {
        var items = load()
        items.insert(.make(level: level, title: title, body: body), at: 0)
        if items.count > 30 {
            items = Array(items.prefix(30))
        }
        if let data = try? JSONEncoder().encode(items),
           let raw = String(data: data, encoding: .utf8) {
            OuroborosWidgetSharedConfig.defaults.set(raw, forKey: key)
        }
    }
}

private struct NativeCommandCenterView: View {
    let config: WidgetNativeConfig
    let privacyLockEnabled: Bool
    @State private var snapshot: NativeStatusSnapshot?
    @State private var statusText = "未取得"
    @State private var diagnostics = "未実行"
    @State private var liveActivityStatus = "未開始"
    @State private var liveActivityDetail = "iOS設定とHost/tokenを確認してから開始できます。"
    @State private var isLoading = false
    @State private var unlocked = false
    @AppStorage(NativeNotificationHistoryStore.key, store: OuroborosWidgetSharedConfig.defaults) private var historyRaw: String = ""

    var body: some View {
        Group {
            if privacyLockEnabled && !unlocked {
                privacyGate
            } else {
                commandContent
            }
        }
        .navigationTitle("Command")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await refreshAll() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
            }
        }
        .task {
            if !privacyLockEnabled {
                await refreshAll()
            }
        }
    }

    private var commandContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                hero
                liveActivityPanel
                diagnosticsPanel
                widgetPresetPanel
                notificationHistoryPanel
            }
            .padding(16)
        }
        .background(Color(uiColor: .systemGroupedBackground))
    }

    private var privacyGate: some View {
        VStack(spacing: 18) {
            Image(systemName: "faceid")
                .font(.system(size: 54, weight: .bold))
                .foregroundStyle(.blue)
            Text("Command Center は保護中")
                .font(.title2.bold())
            Text("口座・通知・運用状態を表示するため、Face ID / パスコードで解除します。")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("解除する") {
                Task { await unlockWithBiometrics() }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(28)
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("OUROBOROS COMMAND")
                        .font(.caption.weight(.black))
                        .tracking(1.8)
                        .foregroundStyle(.white.opacity(0.58))
                    Text(snapshot?.effective_stage ?? "待機")
                        .font(.system(size: 32, weight: .black, design: .rounded))
                        .foregroundStyle(.white)
                    Text(statusText)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white.opacity(0.72))
                }
                Spacer()
                commandRing
                    .frame(width: 82, height: 82)
            }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                commandMetric("IBKR", money(snapshot?.ibkr_account?.net_liquidation_jpy), ibkrDetailText, .green)
                commandMetric("bitFlyer", moneyOrPending(snapshot?.bitflyer_account?.jpy ?? snapshot?.balance?.value_jpy), bitflyerDetailText, .orange)
                commandMetric("Daily", "\(money(snapshot?.goal?.pnl_jpy)) / \(money(snapshot?.goal?.goal_jpy))", "残り \(money(snapshot?.goal?.remaining_jpy))", .blue)
                commandMetric("Week", money(snapshot?.weekly?.pnl_jpy_sum), "WR \(pct(snapshot?.weekly?.win_rate_pct))", weeklyTone)
                commandMetric("Shadow", snapshot?.drift?.status ?? "-", "あと\(snapshot?.drift?.remaining_samples ?? 0)件", shadowTone)
            }
        }
        .padding(18)
        .background(
            LinearGradient(
                colors: [Color(red: 0.34, green: 0.40, blue: 0.54), Color(red: 0.07, green: 0.08, blue: 0.13)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 30, style: .continuous)
        )
    }

    private var commandRing: some View {
        ZStack {
            Circle().stroke(.white.opacity(0.18), lineWidth: 10)
            Circle()
                .trim(from: 0, to: max(0.06, min(1, (snapshot?.weekly?.win_rate_pct ?? 0) / 100)))
                .stroke(levelColor, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: 1) {
                Text(snapshot?.runner_alive == true ? "RUN" : "STOP")
                    .font(.caption.weight(.black))
                    .foregroundStyle(levelColor)
                Text(snapshot?.trade_enabled == true ? "ON" : "OFF")
                    .font(.headline.weight(.black))
                    .foregroundStyle(.white)
            }
        }
    }

    private var diagnosticsPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("One Tap Diagnostics", systemImage: "stethoscope")
                .font(.headline)
            Text(diagnostics)
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            HStack {
                Button("診断する") {
                    Task { await runDiagnostics() }
                }
                .buttonStyle(.borderedProminent)
                Button("Widget更新") {
                    WidgetCenter.shared.reloadAllTimelines()
                    NativeNotificationHistoryStore.append(level: "INFO", title: "Widget更新", body: "WidgetKit timeline を再読み込みしました。")
                    historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(16)
        .background(.background, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var liveActivityPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Live Activity", systemImage: "waveform.path.ecg.rectangle")
                    .font(.headline)
                Spacer()
                Text(liveActivityStatus)
                    .font(.caption.weight(.bold))
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(.secondary.opacity(0.12), in: Capsule())
            }
            Text("ロック画面/Dynamic Islandに運用状態を出します。更新はiOS制限に合わせ、まずは手動開始・更新・終了です。")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(liveActivityDetail)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            HStack {
                Button("開始") {
                    Task { await startLiveActivity() }
                }
                .buttonStyle(.borderedProminent)
                Button("更新") {
                    Task { await updateLiveActivity() }
                }
                .buttonStyle(.bordered)
                Button("終了") {
                    Task { await endLiveActivities() }
                }
                .buttonStyle(.bordered)
                Button("状態確認") {
                    refreshLiveActivityStateLabel()
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(16)
        .background(.background, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var widgetPresetPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Widget Presets", systemImage: "square.grid.2x2")
                    .font(.headline)
                Spacer()
                Text("長押しで選択")
                    .font(.caption.weight(.bold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(.green.opacity(0.16), in: Capsule())
                    .foregroundStyle(.green)
            }
            presetRow("Home Small", "黒い口座カード", "残高 / 当日変化 / Cash-Health-Energy")
            presetRow("Home Medium", "詳細カード", "口座 / Cash / Week / Drift / Donut")
            presetRow("Lock Circular", "丸ドーナツ", "OB/SH/DG/WK を中央表示")
            presetRow("Lock Rectangular", "横長ピル", "口座額 + 当日%")
            Text("実際の表示内容は、配置済みWidgetを長押しして `ウィジェットを編集` から `自動 / 口座 / シャドウ / 日次 / 週次` を選べます。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .background(.background, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var notificationHistoryPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Notification Log", systemImage: "bell.badge")
                    .font(.headline)
                Spacer()
                Text("\(historyItems.count)")
                    .font(.caption.weight(.black))
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(.secondary.opacity(0.12), in: Capsule())
            }
            if historyItems.isEmpty {
                Text("まだネイティブ側の通知履歴はありません。Web表示失敗、テスト通知、ntfy送信、Widget更新がここに残ります。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(historyItems.prefix(8)) { item in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(item.level)
                                .font(.caption2.weight(.black))
                                .foregroundStyle(color(for: item.level))
                            Text(item.dateText)
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                            Spacer()
                        }
                        Text(item.title)
                            .font(.subheadline.weight(.bold))
                        Text(item.body)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    .padding(10)
                    .background(.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
            }
        }
        .padding(16)
        .background(.background, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var historyItems: [NativeNotificationEvent] {
        guard let data = historyRaw.data(using: .utf8),
              let items = try? JSONDecoder().decode([NativeNotificationEvent].self, from: data) else {
            return NativeNotificationHistoryStore.load()
        }
        return items
    }

    private func commandMetric(_ title: String, _ value: String, _ detail: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title.uppercased())
                .font(.caption2.weight(.black))
                .tracking(1.2)
                .foregroundStyle(.white.opacity(0.48))
            Text(value)
                .font(.system(size: 20, weight: .black, design: .rounded))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.58)
            Text(detail)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.white.opacity(0.68))
                .lineLimit(1)
        }
        .padding(12)
        .background(.white.opacity(0.10), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private func presetRow(_ title: String, _ kind: String, _ detail: String) -> some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(red: 0.10, green: 0.11, blue: 0.15))
                .frame(width: title.contains("Lock") ? 54 : 62, height: title.contains("Small") ? 54 : 40)
                .overlay(
                    Circle()
                        .stroke(.green.opacity(0.8), lineWidth: 5)
                        .frame(width: title.contains("Lock") ? 28 : 30, height: title.contains("Lock") ? 28 : 30)
                )
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.black))
                Text(kind)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
        }
    }

    private func refreshAll() async {
        await loadStatus()
        refreshLiveActivityStateLabel()
    }

    private func loadStatus() async {
        guard let url = config.statusURL else {
            statusText = "Host/token 未設定"
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            snapshot = try JSONDecoder().decode(NativeStatusSnapshot.self, from: data)
            statusText = "更新 \(snapshot?.generated_at_jst ?? "-") / state \(snapshot?.state_updated_at ?? "-")"
        } catch {
            statusText = "取得失敗: \(error.localizedDescription)"
            NativeNotificationHistoryStore.append(level: "WARN", title: "Command取得失敗", body: error.localizedDescription)
            historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
        }
    }

    private func runDiagnostics() async {
        var lines: [String] = []
        if let statusURL = config.statusURL {
            lines.append(await probe("Widget JSON", url: statusURL))
        } else {
            lines.append("Widget JSON: Host/token未設定")
        }
        if let dashboardURL = config.dashboardURL {
            lines.append(await probe("Dashboard", url: dashboardURL))
        } else {
            lines.append("Dashboard: Host未設定")
        }
        lines.append("Runner: \(snapshot?.runner_alive == true ? "OK" : "CHECK")")
        lines.append("Trade: \(snapshot?.trade_enabled == true ? "ON" : "OFF")")
        lines.append("Shadow: \(snapshot?.drift?.status ?? "-")")
        diagnostics = lines.joined(separator: "\n")
        NativeNotificationHistoryStore.append(level: "INFO", title: "診断完了", body: diagnostics)
        historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
    }

    private func startLiveActivity() async {
        guard config.isReady else {
            liveActivityStatus = "未設定"
            liveActivityDetail = "SettingsでHost/tokenを保存してください。"
            NativeNotificationHistoryStore.append(level: "WARN", title: "Live Activity未開始", body: liveActivityDetail)
            historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
            return
        }
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            liveActivityStatus = "無効"
            liveActivityDetail = "iOS設定でLive ActivitiesがOFFです。設定アプリ側で有効化してください。"
            NativeNotificationHistoryStore.append(level: "WARN", title: "Live Activity", body: liveActivityDetail)
            historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
            return
        }
        if !Activity<OuroborosLiveActivityAttributes>.activities.isEmpty {
            await updateLiveActivity()
            liveActivityDetail = "既存のLive Activityを現在状態で更新しました。"
            return
        }
        await loadStatus()
        let attributes = OuroborosLiveActivityAttributes(name: "Ouroboros")
        let content = ActivityContent(state: liveActivityState(), staleDate: Date().addingTimeInterval(30 * 60))
        do {
            _ = try Activity.request(attributes: attributes, content: content, pushType: nil)
            liveActivityStatus = "開始済み"
            liveActivityDetail = "ロック画面/Dynamic Islandに表示中です。状態変化後は更新を押してください。"
            NativeNotificationHistoryStore.append(level: "INFO", title: "Live Activity開始", body: "ロック画面/Dynamic Island表示を開始しました。")
        } catch {
            liveActivityStatus = "開始失敗"
            liveActivityDetail = "開始失敗: \(error.localizedDescription)"
            NativeNotificationHistoryStore.append(level: "WARN", title: "Live Activity開始失敗", body: error.localizedDescription)
        }
        historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
    }

    private func updateLiveActivity() async {
        await loadStatus()
        let activities = Activity<OuroborosLiveActivityAttributes>.activities
        guard !activities.isEmpty else {
            liveActivityStatus = "未開始"
            liveActivityDetail = "開始中のLive Activityがありません。先に開始を押してください。"
            return
        }
        let content = ActivityContent(state: liveActivityState(), staleDate: Date().addingTimeInterval(30 * 60))
        for activity in activities {
            await activity.update(content)
        }
        liveActivityStatus = "更新済み"
        liveActivityDetail = "\(activities.count)件のLive Activityを現在状態で更新しました。"
        NativeNotificationHistoryStore.append(level: "INFO", title: "Live Activity更新", body: "現在のwidget-statusで更新しました。")
        historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
    }

    private func endLiveActivities() async {
        let activities = Activity<OuroborosLiveActivityAttributes>.activities
        let content = ActivityContent(state: liveActivityState(), staleDate: nil)
        for activity in activities {
            await activity.end(content, dismissalPolicy: .immediate)
        }
        liveActivityStatus = "終了"
        liveActivityDetail = "Live Activityを終了しました。必要な時だけ再度開始してください。"
        NativeNotificationHistoryStore.append(level: "INFO", title: "Live Activity終了", body: "ロック画面/Dynamic Island表示を終了しました。")
        historyRaw = OuroborosWidgetSharedConfig.defaults.string(forKey: NativeNotificationHistoryStore.key) ?? ""
    }

    private func refreshLiveActivityStateLabel() {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            liveActivityStatus = "無効"
            liveActivityDetail = "iOS設定でLive ActivitiesがOFFです。設定アプリ側で有効化してください。"
            return
        }
        let activeCount = Activity<OuroborosLiveActivityAttributes>.activities.count
        if activeCount > 0 {
            liveActivityStatus = "起動中 \(activeCount)"
            liveActivityDetail = "ロック画面/Dynamic Islandに表示中です。状態変化後は更新を押してください。"
        } else if config.isReady {
            liveActivityStatus = "開始可"
            liveActivityDetail = "開始を押すと現在のwidget-statusをロック画面/Dynamic Islandへ出します。"
        } else {
            liveActivityStatus = "未設定"
            liveActivityDetail = "SettingsでHost/tokenを保存してください。"
        }
    }

    private func liveActivityState() -> OuroborosLiveActivityAttributes.ContentState {
        let nowFormatter = DateFormatter()
        nowFormatter.locale = Locale(identifier: "ja_JP")
        nowFormatter.dateFormat = "HH:mm"
        return OuroborosLiveActivityAttributes.ContentState(
            level: snapshot?.status_level ?? "WAIT",
            stage: snapshot?.effective_stage ?? "Ouroboros",
            tradeText: snapshot?.trade_enabled == true ? "取引ON" : "取引OFF",
            runnerText: snapshot?.runner_alive == true ? "bot稼働" : "bot停止",
            balanceText: accountBalanceText,
            dailyText: money(snapshot?.goal?.pnl_jpy),
            weeklyText: money(snapshot?.weekly?.pnl_jpy_sum),
            shadowText: snapshot?.drift?.status ?? "-",
            updatedAt: nowFormatter.string(from: Date())
        )
    }

    private func probe(_ label: String, url: URL) async -> String {
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            return "\(label): HTTP \(code)"
        } catch {
            return "\(label): NG \(error.localizedDescription)"
        }
    }

    private func unlockWithBiometrics() async {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            unlocked = true
            return
        }
        do {
            let ok = try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Ouroboros Command Center を開きます")
            unlocked = ok
            if ok { await refreshAll() }
        } catch {
            unlocked = false
        }
    }

    private var levelColor: Color {
        switch snapshot?.status_level {
        case "ALERT": return .red
        case "WARN", "WATCH": return .orange
        default: return .green
        }
    }

    private var weeklyTone: Color {
        (snapshot?.weekly?.pnl_jpy_sum ?? 0) >= 0 ? .green : .orange
    }

    private var ibkrDetailText: String {
        guard let account = snapshot?.ibkr_account, account.available == true else {
            return "未取得"
        }
        let accountId = account.account_id?.isEmpty == false ? account.account_id! : "IBKR"
        let stale = account.stale == true ? "STALE" : "LIVE"
        return "\(accountId) / \(stale)"
    }

    private var bitflyerDetailText: String {
        guard let account = snapshot?.bitflyer_account, account.available == true else {
            let error = snapshot?.bitflyer_account?.error ?? snapshot?.balance?.label ?? "未取得"
            return error.isEmpty ? "未取得" : error
        }
        let label = account.label?.isEmpty == false ? account.label! : "bitFlyer"
        return "\(label) / \(account.updated_at ?? "-")"
    }

    private var accountBalanceText: String {
        moneyOrPending(snapshot?.ibkr_account?.net_liquidation_jpy ?? snapshot?.bitflyer_account?.jpy ?? snapshot?.balance?.value_jpy)
    }

    private var shadowTone: Color {
        (snapshot?.drift?.status == "INSUFFICIENT") ? .orange : .green
    }

    private func color(for level: String) -> Color {
        switch level {
        case "CRITICAL": return .red
        case "WARN": return .orange
        default: return .blue
        }
    }

    private func money(_ value: Double?) -> String {
        let n = value ?? 0
        let absValue = abs(n)
        let sign = n < 0 ? "-" : ""
        if absValue >= 10000 {
            return "\(sign)¥\((absValue / 10000).formatted(.number.precision(.fractionLength(1))))万"
        }
        return "\(sign)¥\(Int(absValue.rounded()).formatted())"
    }

    private func moneyOrPending(_ value: Double?) -> String {
        guard let value else { return "未取得" }
        return money(value)
    }

    private func pct(_ value: Double?) -> String {
        "\((value ?? 0).formatted(.number.precision(.fractionLength(1))))%"
    }
}

private struct NativeSetupRequiredView: View {
    let config: WidgetNativeConfig
    let tab: WidgetNativeTab

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("最初に接続設定が必要です", systemImage: "iphone.badge.exclamationmark")
                .font(.title3.bold())
            Text("この native app は売買ロジックを持たず、既存の widget-react / unified dashboard を安全に包む shell です。")
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 10) {
                ForEach(config.helperLines, id: \.self) { line in
                    Text(line)
                        .font(.subheadline)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            Text(tab == .dashboard ? "Dashboard は Settings タブで Host を入れると使えます。" : "Settings タブで Host と Token を入れると使えます。")
                .font(.headline)
            if tab == .dashboard, config.normalizedOrigin.isEmpty {
                Text("例: http://100.66.216.5")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct NativeSettingsView: View {
    @Binding var hostInput: String
    @Binding var token: String
    @Binding var notificationsEnabled: Bool
    @Binding var ntfyTopicURL: String
    @Binding var ntfyBearerToken: String
    @Binding var privacyLockEnabled: Bool
    let config: WidgetNativeConfig
    @Environment(\.openURL) private var openURL
    @State private var notificationStatusText = "未確認"
    @State private var ntfyStatusText = "未確認"

    var body: some View {
        Form {
            Section("Connection") {
                TextField("例: http://100.66.216.5", text: $hostInput)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled(true)
                SecureField("Widget token", text: $token)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled(true)
                HStack {
                    Text("Host")
                    Spacer()
                    Text(config.normalizedOrigin.isEmpty ? "未設定" : config.normalizedOrigin)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.trailing)
                }
                HStack {
                    Text("Token")
                    Spacer()
                    Text(config.redactedTokenPreview)
                        .foregroundStyle(.secondary)
                }
            }

            Section("Preview URLs") {
                previewRow("Overview", value: config.redactedURLString(for: .overview))
                previewRow("Reflection", value: config.redactedURLString(for: .reflection))
                previewRow("Trades", value: config.redactedURLString(for: .trades))
                previewRow("Dashboard", value: config.redactedURLString(for: .dashboard))
            }

            Section("Notifications") {
                Toggle("Native通知を有効化", isOn: $notificationsEnabled)
                Toggle("Command CenterをFace IDで保護", isOn: $privacyLockEnabled)
                HStack {
                    Text("Permission")
                    Spacer()
                    Text(notificationStatusText)
                        .foregroundStyle(.secondary)
                }
                Button("通知許可を確認") {
                    Task {
                        notificationStatusText = await OuroborosNativeNotifier.shared.requestPermissionText()
                    }
                }
                Button("テスト通知を送る") {
                    notificationsEnabled = true
                    Task {
                        notificationStatusText = await OuroborosNativeNotifier.shared.requestPermissionText()
                        await OuroborosNativeNotifier.shared.send(
                            title: "Ouroboros 通知テスト",
                            body: "ネイティブ通知の受け皿は有効です。",
                            interruptionLevel: .active
                        )
                        NativeNotificationHistoryStore.append(level: "INFO", title: "通知テスト", body: "ネイティブ通知の受け皿を確認しました。")
                    }
                }
                Text("現段階では、アプリ表示中の接続失敗を30分抑制で通知します。完全なバックグラウンドPushはAPNs/サーバー側の追加が必要です。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Free Push / ntfy") {
                TextField("https://ntfy.sh/your-topic", text: $ntfyTopicURL)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled(true)
                SecureField("Bearer token 任意", text: $ntfyBearerToken)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled(true)
                HStack {
                    Text("Status")
                    Spacer()
                    Text(ntfyStatusText)
                        .foregroundStyle(.secondary)
                }
                Button("ntfyテスト送信") {
                    Task {
                        ntfyStatusText = await OuroborosNtfyNotifier.shared.send(
                            topicURLString: ntfyTopicURL,
                            bearerToken: ntfyBearerToken,
                            body: "Ouroboros native app からの無料ntfyテスト通知です。"
                        )
                        NativeNotificationHistoryStore.append(level: ntfyStatusText.contains("OK") ? "INFO" : "WARN", title: "ntfyテスト", body: ntfyStatusText)
                    }
                }
                Button("ntfy購読ページを開く") {
                    if let url = URL(string: ntfyTopicURL.trimmingCharacters(in: .whitespacesAndNewlines)), !ntfyTopicURL.isEmpty {
                        openURL(url)
                    }
                }
                .disabled(URL(string: ntfyTopicURL.trimmingCharacters(in: .whitespacesAndNewlines)) == nil)
                Text("無料で外部Pushを使う場合は、iPhoneのntfyアプリで同じtopicを購読します。Ouroboros本体の既存ntfy通知と同じtopicを入れると、Bot/IBKR/日次通知をそのまま受けられます。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Notes") {
                Text("Token は repo に入れず、この app のローカル設定だけに保存します。")
                Text("Host には Tailscale IP か Tailscale DNS 名の origin だけを入れてください。")
                Text("Dashboard は token 不要ですが、Overview / Reflection は token が必要です。")
            }
        }
        .navigationTitle("Settings")
        .task {
            notificationStatusText = await OuroborosNativeNotifier.shared.currentPermissionText()
        }
    }

    @ViewBuilder
    private func previewRow(_ title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.subheadline.weight(.semibold))
            Text(value)
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
        .padding(.vertical, 2)
    }
}

private final class OuroborosNtfyNotifier {
    static let shared = OuroborosNtfyNotifier()

    private init() {}

    func send(topicURLString: String, bearerToken: String, body: String) async -> String {
        let trimmedURL = topicURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmedURL), !trimmedURL.isEmpty else {
            return "URL未設定"
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.httpBody = Data(body.utf8)
        request.setValue("text/plain; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue("Ouroboros Native", forHTTPHeaderField: "Title")
        request.setValue("iphone", forHTTPHeaderField: "Tags")
        let bearer = bearerToken.trimmingCharacters(in: .whitespacesAndNewlines)
        if !bearer.isEmpty {
            request.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse {
                return (200..<300).contains(http.statusCode) ? "HTTP \(http.statusCode) OK" : "HTTP \(http.statusCode)"
            }
            return "送信済み"
        } catch {
            return "失敗: \(error.localizedDescription)"
        }
    }
}

private final class OuroborosNativeNotifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = OuroborosNativeNotifier()
    private let center = UNUserNotificationCenter.current()

    private override init() {
        super.init()
        center.delegate = self
    }

    func currentPermissionText() async -> String {
        let settings = await center.notificationSettings()
        return text(for: settings.authorizationStatus)
    }

    func requestPermissionText() async -> String {
        do {
            _ = try await center.requestAuthorization(options: [.alert, .sound, .badge])
            let settings = await center.notificationSettings()
            return text(for: settings.authorizationStatus)
        } catch {
            return "失敗: \(error.localizedDescription)"
        }
    }

    func send(title: String, body: String, interruptionLevel: UNNotificationInterruptionLevel) async {
        let settings = await center.notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            return
        }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.interruptionLevel = interruptionLevel
        let request = UNNotificationRequest(identifier: "ouroboros-native-\(UUID().uuidString)", content: content, trigger: nil)
        try? await center.add(request)
    }

    private func text(for status: UNAuthorizationStatus) -> String {
        switch status {
        case .authorized:
            return "許可済み"
        case .provisional:
            return "仮許可"
        case .denied:
            return "拒否"
        case .notDetermined:
            return "未確認"
        case .ephemeral:
            return "一時許可"
        @unknown default:
            return "不明"
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }
}
