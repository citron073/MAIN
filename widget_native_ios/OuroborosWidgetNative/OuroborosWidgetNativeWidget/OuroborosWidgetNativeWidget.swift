import SwiftUI
import WidgetKit
import AppIntents
import ActivityKit

enum OuroborosWidgetDisplayMode: String, AppEnum {
    case auto
    case account
    case shadow
    case daily
    case weekly

    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "表示内容")

    static var caseDisplayRepresentations: [OuroborosWidgetDisplayMode: DisplayRepresentation] = [
        .auto: "自動",
        .account: "口座",
        .shadow: "シャドウ",
        .daily: "日次",
        .weekly: "週次",
    ]
}

struct OuroborosWidgetConfigurationIntent: WidgetConfigurationIntent {
    static var title: LocalizedStringResource = "Ouroboros表示"
    static var description = IntentDescription("ウィジェットに表示する内容を選びます。")

    @Parameter(title: "表示内容", default: .auto)
    var displayMode: OuroborosWidgetDisplayMode
}

private struct WidgetStatusSnapshot: Decodable {
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

    struct PnLCurve: Decodable {
        var available: Bool?
        var closed_n: Int?
        var points: [Double]?
        var bars: [Double]?
        var total_pnl_jpy: Double?
        var win_rate_pct: Double?
        var best_pnl_jpy: Double?
        var worst_pnl_jpy: Double?
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
    var pnl_curve: PnLCurve?
    var balance: Balance?
    var bitflyer_account: BitflyerAccount?
    var ibkr_account: IBKRAccount?
}

private struct OuroborosWidgetEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetStatusSnapshot?
    let message: String
    let overviewURL: URL?
    let displayMode: OuroborosWidgetDisplayMode

    var stage: String {
        snapshot?.effective_stage ?? "Ouroboros"
    }

    var level: String {
        snapshot?.status_level ?? "WAIT"
    }

    var tradeText: String {
        (snapshot?.trade_enabled ?? false) ? "取引ON" : "取引OFF"
    }

    var runnerText: String {
        (snapshot?.runner_alive ?? false) ? "bot稼働" : "bot停止"
    }
}

private struct OuroborosWidgetProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> OuroborosWidgetEntry {
        sampleEntry(message: "Preview", displayMode: .auto)
    }

    func snapshot(for configuration: OuroborosWidgetConfigurationIntent, in context: Context) async -> OuroborosWidgetEntry {
        sampleEntry(message: "Snapshot", displayMode: configuration.displayMode)
    }

    func timeline(for configuration: OuroborosWidgetConfigurationIntent, in context: Context) async -> Timeline<OuroborosWidgetEntry> {
        let entry = await loadEntry(displayMode: configuration.displayMode)
        let next = Calendar.current.date(byAdding: .minute, value: 15, to: Date()) ?? Date().addingTimeInterval(900)
        return Timeline(entries: [entry], policy: .after(next))
    }

    private func sampleEntry(message: String, displayMode: OuroborosWidgetDisplayMode) -> OuroborosWidgetEntry {
        let snapshot = WidgetStatusSnapshot(
            generated_at_jst: nil,
            state_updated_at: nil,
            effective_stage: "LIVE",
            status_level: "WATCH",
            trade_enabled: true,
            runner_alive: true,
            goal: .init(pnl_jpy: 0, goal_jpy: 100, remaining_jpy: 100, closed_n: 0),
            weekly: .init(pnl_jpy_sum: -60, win_rate_pct: 33.3, closed_n: 3),
            drift: .init(status: "INSUFFICIENT", remaining_samples: 2),
            pnl_curve: .init(available: true, closed_n: 6, points: [0, -18, 12, 28, -4, 22, -6], bars: [-18, 30, 16, -32, 26, -28], total_pnl_jpy: -6, win_rate_pct: 50, best_pnl_jpy: 30, worst_pnl_jpy: -32),
            balance: .init(label: "取得待ち", value_jpy: nil, available_jpy: nil),
            bitflyer_account: nil,
            ibkr_account: nil
        )
        return OuroborosWidgetEntry(date: Date(), snapshot: snapshot, message: message, overviewURL: nil, displayMode: displayMode)
    }

    private func loadEntry(displayMode: OuroborosWidgetDisplayMode) async -> OuroborosWidgetEntry {
        let defaults = OuroborosWidgetSharedConfig.defaults
        let hostInput = defaults.string(forKey: OuroborosWidgetSharedConfig.hostKey) ?? ""
        let token = defaults.string(forKey: OuroborosWidgetSharedConfig.tokenKey) ?? ""
        guard let origin = normalizedOrigin(hostInput), !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return OuroborosWidgetEntry(date: Date(), snapshot: nil, message: "SettingsでHost/tokenを設定", overviewURL: nil, displayMode: displayMode)
        }
        guard var components = URLComponents(string: "\(origin):8787/widget-status.json") else {
            return OuroborosWidgetEntry(date: Date(), snapshot: nil, message: "Host設定を確認", overviewURL: nil, displayMode: displayMode)
        }
        components.queryItems = [URLQueryItem(name: "token", value: token)]
        guard let url = components.url else {
            return OuroborosWidgetEntry(date: Date(), snapshot: nil, message: "URL生成失敗", overviewURL: nil, displayMode: displayMode)
        }

        let overviewURL = URL(string: "\(origin):8787/widget-react/index.html?token=\(urlEncoded(token))&scene=overview&native=1")
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let snapshot = try JSONDecoder().decode(WidgetStatusSnapshot.self, from: data)
            return OuroborosWidgetEntry(date: Date(), snapshot: snapshot, message: "OK", overviewURL: overviewURL, displayMode: displayMode)
        } catch {
            return OuroborosWidgetEntry(date: Date(), snapshot: nil, message: "通信待機 / Tailscale確認", overviewURL: overviewURL, displayMode: displayMode)
        }
    }

    private func normalizedOrigin(_ input: String) -> String? {
        let raw = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return nil }
        let prefixed = raw.contains("://") ? raw : "http://\(raw)"
        guard let components = URLComponents(string: prefixed),
              let scheme = components.scheme,
              let host = components.host else {
            return nil
        }
        return "\(scheme)://\(host)"
    }

    private func urlEncoded(_ token: String) -> String {
        token.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? token
    }
}

private struct MiniPnLSparkline: View {
    let points: [Double]
    let color: Color
    var fill: Bool = true

    var body: some View {
        GeometryReader { proxy in
            let safePoints = points.filter { $0.isFinite }
            let plotted = safePoints.count >= 2 ? safePoints : [0, 0]
            ZStack {
                SparklineShape(points: plotted)
                    .stroke(.white.opacity(0.13), style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round))
                if fill {
                    SparklineFillShape(points: plotted)
                        .fill(
                            LinearGradient(
                                colors: [color.opacity(0.24), color.opacity(0.02)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                }
                SparklineShape(points: plotted)
                    .stroke(color, style: StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round))
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
    }
}

private struct SparklineShape: Shape {
    let points: [Double]

    func path(in rect: CGRect) -> Path {
        let pts = points.filter { $0.isFinite }
        guard pts.count >= 2 else {
            var path = Path()
            path.move(to: CGPoint(x: rect.minX, y: rect.midY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return path
        }
        let minValue = pts.min() ?? 0
        let maxValue = pts.max() ?? 1
        let range = max(1, maxValue - minValue)
        let step = rect.width / CGFloat(max(1, pts.count - 1))
        var path = Path()
        for (index, value) in pts.enumerated() {
            let x = rect.minX + CGFloat(index) * step
            let yRatio = CGFloat((value - minValue) / range)
            let y = rect.maxY - yRatio * rect.height
            if index == 0 {
                path.move(to: CGPoint(x: x, y: y))
            } else {
                path.addLine(to: CGPoint(x: x, y: y))
            }
        }
        return path
    }
}

private struct SparklineFillShape: Shape {
    let points: [Double]

    func path(in rect: CGRect) -> Path {
        var path = SparklineShape(points: points).path(in: rect)
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

private struct OuroborosWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: OuroborosWidgetEntry

    var body: some View {
        switch family {
        case .accessoryCircular:
            circular
        case .accessoryRectangular:
            rectangular
        case .accessoryInline:
            inline
        case .systemMedium:
            medium
        default:
            small
        }
    }

    private var small: some View {
        GeometryReader { proxy in
            ZStack {
                smallCardBackground
                VStack(alignment: .leading, spacing: 7) {
                    HStack(spacing: 5) {
                        Text("OB")
                            .font(.system(size: 9, weight: .black, design: .rounded))
                            .foregroundStyle(.black)
                            .padding(.horizontal, 4)
                            .padding(.vertical, 2)
                            .background(Color(red: 0.36, green: 0.82, blue: 0.55), in: RoundedRectangle(cornerRadius: 4, style: .continuous))
                        Text("Ouroboros")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundStyle(.white.opacity(0.68))
                            .lineLimit(1)
                            .minimumScaleFactor(0.7)
                        Spacer(minLength: 0)
                        Text("TODAY")
                            .font(.system(size: 9, weight: .black, design: .rounded))
                            .tracking(0.8)
                            .foregroundStyle(.white.opacity(0.48))
                    }
                    Text(balanceText)
                        .font(.system(size: proxy.size.width < 150 ? 25 : 30, weight: .black, design: .rounded))
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .minimumScaleFactor(0.55)
                    Text("\(dailyDeltaText) · \(dailyPctText)")
                        .font(.system(size: 11, weight: .heavy, design: .rounded))
                        .foregroundStyle(dailyTone)
                        .lineLimit(1)
                        .minimumScaleFactor(0.65)
                    MiniPnLSparkline(points: pnlPoints, color: pnlTone)
                        .frame(height: 20)
                    Spacer(minLength: 0)
                    HStack(alignment: .center, spacing: 8) {
                        segmentedDonut(size: 45, thickness: 9)
                        VStack(alignment: .leading, spacing: 2) {
                            legendRow(color: Color(red: 0.72, green: 0.77, blue: 0.84), label: "Cash", value: cashShareText)
                            legendRow(color: Color(red: 0.39, green: 0.80, blue: 0.65), label: "Health", value: healthShareText)
                            legendRow(color: Color(red: 0.94, green: 0.52, blue: 0.28), label: "Energy", value: energyShareText)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(12)
            }
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        }
        .widgetURL(entry.overviewURL)
    }

    private var medium: some View {
        ZStack {
            mediumCardBackground
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 7) {
                    HStack(spacing: 6) {
                        Text("OB")
                            .font(.system(size: 10, weight: .black, design: .rounded))
                            .foregroundStyle(.black)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 2)
                            .background(Color(red: 0.36, green: 0.82, blue: 0.55), in: RoundedRectangle(cornerRadius: 5, style: .continuous))
                        Text("Ouroboros")
                            .font(.system(size: 13, weight: .bold, design: .rounded))
                            .foregroundStyle(.white.opacity(0.72))
                        Spacer(minLength: 0)
                        Text(entry.level)
                            .font(.system(size: 10, weight: .black, design: .rounded))
                            .foregroundStyle(levelColor)
                    }
                    Text(balanceText)
                        .font(.system(size: 34, weight: .black, design: .rounded))
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .minimumScaleFactor(0.48)
                    Text("\(entry.tradeText) ・ \(entry.runnerText) ・ \(entry.snapshot?.drift?.status ?? entry.level)")
                        .font(.system(size: 12, weight: .bold, design: .rounded))
                        .foregroundStyle(.white.opacity(0.72))
                        .lineLimit(1)
                        .minimumScaleFactor(0.65)
                    MiniPnLSparkline(points: pnlPoints, color: pnlTone)
                        .frame(height: 28)
                        .padding(.vertical, 1)
                    HStack(spacing: 8) {
                        miniMetric("P/L", pnlSummaryText, tone: pnlTone)
                        miniMetric("WEEK", jpy(entry.snapshot?.weekly?.pnl_jpy_sum), tone: weeklyTone)
                        miniMetric("DRIFT", "\(entry.snapshot?.drift?.remaining_samples ?? 0)件")
                    }
                }
                Spacer(minLength: 0)
                VStack(spacing: 5) {
                    segmentedDonut(size: 68, thickness: 10)
                    Text(dailyPctText)
                        .font(.system(size: 11, weight: .black, design: .rounded))
                        .foregroundStyle(dailyTone)
                }
            }
            .padding(14)
        }
        .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
        .widgetURL(entry.overviewURL)
    }

    private var legacyMedium: some View {
        ZStack {
            widgetBackground
            VStack(alignment: .leading, spacing: 9) {
                header
                HStack(alignment: .center, spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(modeLabel)
                            .font(.system(size: 9, weight: .black))
                            .tracking(1.4)
                            .foregroundStyle(.white.opacity(0.48))
                        Text(primaryValue)
                            .font(.system(size: 36, weight: .black, design: .rounded))
                            .lineLimit(1)
                            .minimumScaleFactor(0.48)
                        Text(primaryDetail)
                            .font(.system(size: 12, weight: .bold, design: .rounded))
                            .foregroundStyle(.white.opacity(0.76))
                            .lineLimit(1)
                            .minimumScaleFactor(0.68)
                    }
                    Spacer(minLength: 0)
                    ZStack {
                        ring(value: ringProgress, color: modeColor)
                        VStack(spacing: 0) {
                            Text(modeShort)
                                .font(.system(size: 13, weight: .black, design: .rounded))
                                .foregroundStyle(modeColor)
                            Text(circularValue)
                                .font(.system(size: 12, weight: .heavy, design: .rounded))
                                .lineLimit(1)
                                .minimumScaleFactor(0.55)
                        }
                    }
                    .frame(width: 72, height: 72)
                }
                HStack(spacing: 7) {
                    ForEach(detailCapsules.prefix(3), id: \.0) { item in
                        capsule(item.0, item.1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .padding(.horizontal, 11)
            .padding(.vertical, 10)
        }
        .widgetURL(entry.overviewURL)
    }

    private var circular: some View {
        ZStack {
            segmentedDonut(size: 58, thickness: 8)
            Circle()
                .fill(.black.opacity(0.72))
                .padding(12)
            VStack(spacing: 0) {
                Text(lockCircleLabel)
                    .font(.system(size: 11, weight: .black, design: .rounded))
                    .foregroundStyle(.white.opacity(0.92))
                Text(lockCircleValue)
                    .font(.system(size: 13, weight: .black, design: .rounded))
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.55)
            }
        }
        .widgetURL(entry.overviewURL)
    }

    private var rectangular: some View {
        GeometryReader { proxy in
            HStack(spacing: 7) {
                MiniPnLSparkline(points: pnlPoints, color: pnlTone, fill: false)
                    .frame(width: 32, height: 38)
                    .clipped()
                HStack(spacing: 7) {
                    Text("$")
                        .font(.system(size: 15, weight: .black, design: .rounded))
                        .foregroundStyle(.white.opacity(0.74))
                    Text(lockRectMainAmount)
                        .font(.system(size: 21, weight: .black, design: .rounded))
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .minimumScaleFactor(0.55)
                    Divider()
                        .frame(height: 18)
                        .overlay(.white.opacity(0.22))
                    Text(dailyPctText)
                        .font(.system(size: 18, weight: .black, design: .rounded))
                        .foregroundStyle(dailyTone)
                        .lineLimit(1)
                        .minimumScaleFactor(0.58)
                }
                .padding(.horizontal, 14)
                .frame(maxWidth: proxy.size.width - 20, minHeight: 46)
                .background(
                    Capsule(style: .continuous)
                        .fill(Color(red: 0.42, green: 0.43, blue: 0.47).opacity(0.82))
                )
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .widgetURL(entry.overviewURL)
    }

    private var inline: some View {
        Text("Ouro \(lockMainText) \(primaryValue) W \(jpy(entry.snapshot?.weekly?.pnl_jpy_sum))")
    }

    private var header: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(levelColor)
                .frame(width: 8, height: 8)
            Text(entry.level)
                .font(.caption2.weight(.black))
                .foregroundStyle(levelColor)
            Spacer(minLength: 0)
            Text("OURO")
                .font(.caption2.weight(.black))
                .foregroundStyle(.white.opacity(0.45))
        }
    }

    private func capsule(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(.system(size: 8, weight: .black))
                .foregroundStyle(.white.opacity(0.48))
            Text(value)
                .font(.caption.weight(.black))
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .padding(.vertical, 7)
        .padding(.horizontal, 9)
        .background(.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 13, style: .continuous))
    }

    private func miniMetric(_ label: String, _ value: String, tone: Color = .white) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: 8, weight: .black, design: .rounded))
                .tracking(0.8)
                .foregroundStyle(.white.opacity(0.48))
            Text(value)
                .font(.system(size: 12, weight: .black, design: .rounded))
                .foregroundStyle(tone)
                .lineLimit(1)
                .minimumScaleFactor(0.65)
        }
        .padding(.vertical, 7)
        .padding(.horizontal, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.white.opacity(0.10), in: RoundedRectangle(cornerRadius: 13, style: .continuous))
    }

    private func legendRow(color: Color, label: String, value: String) -> some View {
        HStack(spacing: 5) {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(color)
                .frame(width: 7, height: 7)
            Text(label)
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .foregroundStyle(.white.opacity(0.86))
                .lineLimit(1)
            Text(value)
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .foregroundStyle(.white.opacity(0.52))
                .lineLimit(1)
                .minimumScaleFactor(0.65)
        }
    }

    private func segmentedDonut(size: CGFloat, thickness: CGFloat) -> some View {
        let cash = max(0.02, min(0.96, cashShare))
        let health = max(0.01, min(0.20, healthShare))
        let energy = max(0.01, min(0.20, energyShare))
        let total = cash + health + energy
        let cashEnd = cash / total
        let healthEnd = cashEnd + health / total
        return ZStack {
            Circle()
                .stroke(Color(red: 0.72, green: 0.77, blue: 0.84).opacity(0.34), lineWidth: thickness)
            Circle()
                .trim(from: 0, to: cashEnd)
                .stroke(Color(red: 0.72, green: 0.77, blue: 0.84), style: StrokeStyle(lineWidth: thickness, lineCap: .butt))
                .rotationEffect(.degrees(-90))
            Circle()
                .trim(from: cashEnd, to: healthEnd)
                .stroke(Color(red: 0.39, green: 0.80, blue: 0.65), style: StrokeStyle(lineWidth: thickness, lineCap: .butt))
                .rotationEffect(.degrees(-90))
            Circle()
                .trim(from: healthEnd, to: 1)
                .stroke(Color(red: 0.94, green: 0.52, blue: 0.28), style: StrokeStyle(lineWidth: thickness, lineCap: .butt))
                .rotationEffect(.degrees(-90))
            Circle()
                .fill(Color(red: 0.08, green: 0.09, blue: 0.12))
                .padding(thickness + 4)
        }
        .frame(width: size, height: size)
    }

    private func ring(value: Double, color: Color) -> some View {
        ZStack {
            Circle()
                .stroke(.white.opacity(0.16), lineWidth: 7)
            Circle()
                .trim(from: 0, to: max(0.06, min(1, value)))
                .stroke(color, style: StrokeStyle(lineWidth: 7, lineCap: .round))
                .rotationEffect(.degrees(-90))
            Circle()
                .fill(.black.opacity(0.38))
                .padding(12)
        }
    }

    private var widgetBackground: some View {
        LinearGradient(
            colors: [Color(red: 0.35, green: 0.42, blue: 0.56), Color(red: 0.10, green: 0.12, blue: 0.19)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var smallCardBackground: some View {
        LinearGradient(
            colors: [Color(red: 0.08, green: 0.08, blue: 0.09), Color(red: 0.03, green: 0.03, blue: 0.04)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .stroke(.white.opacity(0.08), lineWidth: 1)
        )
    }

    private var mediumCardBackground: some View {
        LinearGradient(
            colors: [Color(red: 0.30, green: 0.35, blue: 0.47), Color(red: 0.11, green: 0.13, blue: 0.20)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
        .overlay(
            RoundedRectangle(cornerRadius: 26, style: .continuous)
                .stroke(.white.opacity(0.10), lineWidth: 1)
        )
    }

    private var levelColor: Color {
        switch entry.level {
        case "ALERT": return .red
        case "WARN", "WATCH": return .orange
        default: return .green
        }
    }

    private var balanceText: String {
        jpyOrPending(accountValue)
    }

    private var accountValue: Double? {
        entry.snapshot?.ibkr_account?.net_liquidation_jpy
            ?? entry.snapshot?.bitflyer_account?.jpy
            ?? entry.snapshot?.balance?.value_jpy
    }

    private var accountCashValue: Double? {
        entry.snapshot?.ibkr_account?.available_funds_jpy
            ?? entry.snapshot?.bitflyer_account?.jpy_balance
            ?? entry.snapshot?.bitflyer_account?.available_collateral_jpy
            ?? entry.snapshot?.balance?.available_jpy
    }

    private var dailyPnl: Double {
        entry.snapshot?.goal?.pnl_jpy ?? 0
    }

    private var weeklyPnl: Double {
        entry.snapshot?.weekly?.pnl_jpy_sum ?? 0
    }

    private var pnlPoints: [Double] {
        let raw = entry.snapshot?.pnl_curve?.points ?? []
        let safe = raw.filter { $0.isFinite }
        if safe.count >= 2 { return safe }
        return [0, dailyPnl, dailyPnl + weeklyPnl]
    }

    private var pnlTotal: Double {
        entry.snapshot?.pnl_curve?.total_pnl_jpy ?? weeklyPnl
    }

    private var pnlTone: Color {
        pnlTotal >= 0 ? Color(red: 0.50, green: 1.0, blue: 0.65) : Color(red: 1.0, green: 0.56, blue: 0.58)
    }

    private var pnlSummaryText: String {
        let closed = entry.snapshot?.pnl_curve?.closed_n ?? entry.snapshot?.weekly?.closed_n ?? 0
        return "\(jpy(pnlTotal)) / \(closed)件"
    }

    private var dailyTone: Color {
        dailyPnl >= 0 ? Color(red: 0.50, green: 1.0, blue: 0.65) : Color(red: 1.0, green: 0.56, blue: 0.58)
    }

    private var weeklyTone: Color {
        weeklyPnl >= 0 ? Color(red: 0.50, green: 1.0, blue: 0.65) : Color(red: 1.0, green: 0.56, blue: 0.58)
    }

    private var dailyDeltaText: String {
        let sign = dailyPnl >= 0 ? "▲" : "▼"
        return "\(sign) \(jpy(dailyPnl))"
    }

    private var dailyPctText: String {
        let base = max(1, abs(accountValue ?? 0))
        let pctValue = dailyPnl / base * 100
        let sign = pctValue >= 0 ? "+" : ""
        return "\(sign)\(pctValue.formatted(.number.precision(.fractionLength(2))))%"
    }

    private var cashShare: Double {
        let total = max(1, abs(accountValue ?? 0))
        let cash = abs(accountCashValue ?? 0)
        if cash <= 0 { return 0.995 }
        return max(0.05, min(0.995, cash / total))
    }

    private var healthShare: Double {
        let runnerBonus = (entry.snapshot?.runner_alive ?? false) ? 0.005 : 0.001
        let levelPenalty = entry.level == "ALERT" ? 0.001 : runnerBonus
        return max(0.001, min(0.08, levelPenalty))
    }

    private var energyShare: Double {
        let remaining = Double(entry.snapshot?.drift?.remaining_samples ?? 0)
        return max(0.001, min(0.08, remaining / 200.0))
    }

    private var cashShareText: String {
        pct(cashShare * 100, digits: 1)
    }

    private var healthShareText: String {
        pct(healthShare * 100, digits: 1)
    }

    private var energyShareText: String {
        pct(energyShare * 100, digits: 1)
    }

    private var lockCircleLabel: String {
        switch effectiveMode {
        case .shadow:
            return "SH"
        case .daily:
            return "DG"
        case .weekly:
            return "WK"
        case .auto, .account:
            return "OB"
        }
    }

    private var lockCircleValue: String {
        switch effectiveMode {
        case .shadow:
            return "\(entry.snapshot?.drift?.remaining_samples ?? 0)"
        case .daily:
            return jpy(entry.snapshot?.goal?.pnl_jpy).replacingOccurrences(of: "¥", with: "")
        case .weekly:
            return jpy(entry.snapshot?.weekly?.pnl_jpy_sum).replacingOccurrences(of: "¥", with: "")
        case .auto, .account:
            return shortBalanceNumber
        }
    }

    private var lockRectMainAmount: String {
        switch effectiveMode {
        case .shadow:
            return "\(entry.snapshot?.drift?.remaining_samples ?? 0)"
        case .daily:
            return jpy(entry.snapshot?.goal?.pnl_jpy)
        case .weekly:
            return jpy(entry.snapshot?.weekly?.pnl_jpy_sum)
        case .auto, .account:
            return balanceText
        }
    }

    private var shortBalanceNumber: String {
        guard let raw = accountValue else { return "--" }
        let value = abs(raw)
        if value >= 10000 {
            return (value / 10000).formatted(.number.precision(.fractionLength(0)))
        }
        return Int(value.rounded()).formatted()
    }

    private var effectiveMode: OuroborosWidgetDisplayMode {
        if entry.displayMode != .auto {
            return entry.displayMode
        }
        switch family {
        case .accessoryCircular, .accessoryRectangular, .accessoryInline:
            return .account
        case .systemMedium:
            return .account
        default:
            return .daily
        }
    }

    private var modeLabel: String {
        switch effectiveMode {
        case .auto: return "AUTO"
        case .account: return "ACCOUNT"
        case .shadow: return "SHADOW"
        case .daily: return "DAILY"
        case .weekly: return "WEEKLY"
        }
    }

    private var modeShort: String {
        switch effectiveMode {
        case .auto: return "AU"
        case .account: return "AC"
        case .shadow: return "SH"
        case .daily: return "DY"
        case .weekly: return "WK"
        }
    }

    private var primaryValue: String {
        switch effectiveMode {
        case .auto, .account:
            return balanceText
        case .shadow:
            return entry.snapshot?.drift?.status ?? entry.message
        case .daily:
            return jpy(entry.snapshot?.goal?.pnl_jpy)
        case .weekly:
            return jpy(entry.snapshot?.weekly?.pnl_jpy_sum)
        }
    }

    private var primaryDetail: String {
        switch effectiveMode {
        case .auto, .account:
            return "\(entry.tradeText) ・ \(entry.runnerText) ・ Cash \(jpyOrPending(accountCashValue))"
        case .shadow:
            return "残り \(entry.snapshot?.drift?.remaining_samples ?? 0)件 ・ \(entry.runnerText)"
        case .daily:
            return "目標 \(jpy(entry.snapshot?.goal?.goal_jpy)) ・ 残り \(jpy(entry.snapshot?.goal?.remaining_jpy))"
        case .weekly:
            return "WR \(pct(entry.snapshot?.weekly?.win_rate_pct)) ・ \(entry.snapshot?.weekly?.closed_n ?? 0)件"
        }
    }

    private var secondaryValue: String {
        switch effectiveMode {
        case .auto, .account:
            return jpy(entry.snapshot?.weekly?.pnl_jpy_sum)
        case .shadow:
            return entry.runnerText
        case .daily:
            return "残り \(jpy(entry.snapshot?.goal?.remaining_jpy))"
        case .weekly:
            return "WR \(pct(entry.snapshot?.weekly?.win_rate_pct))"
        }
    }

    private var detailCapsules: [(String, String)] {
        switch effectiveMode {
        case .auto, .account:
            return [("Cash", jpyOrPending(accountCashValue)), ("Week", jpy(entry.snapshot?.weekly?.pnl_jpy_sum)), ("Drift", "\(entry.snapshot?.drift?.remaining_samples ?? 0)件")]
        case .shadow:
            return [("Remain", "\(entry.snapshot?.drift?.remaining_samples ?? 0)件"), ("Runner", entry.runnerText), ("Week", jpy(entry.snapshot?.weekly?.pnl_jpy_sum))]
        case .daily:
            return [("Goal", jpy(entry.snapshot?.goal?.goal_jpy)), ("Closed", "\(entry.snapshot?.goal?.closed_n ?? 0)件"), ("Week", jpy(entry.snapshot?.weekly?.pnl_jpy_sum))]
        case .weekly:
            return [("WR", pct(entry.snapshot?.weekly?.win_rate_pct)), ("Closed", "\(entry.snapshot?.weekly?.closed_n ?? 0)件"), ("Daily", jpy(entry.snapshot?.goal?.pnl_jpy))]
        }
    }

    private var lockTopText: String {
        switch effectiveMode {
        case .shadow:
            return "SH"
        case .daily:
            return "DAY"
        case .weekly:
            return "WEEK"
        case .auto, .account:
            return "RUN"
        }
    }

    private var lockMainText: String {
        switch effectiveMode {
        case .shadow:
            let remaining = entry.snapshot?.drift?.remaining_samples ?? 0
            return remaining > 0 ? "\(remaining)" : "OK"
        case .daily:
            return jpy(entry.snapshot?.goal?.pnl_jpy).replacingOccurrences(of: "¥", with: "")
        case .weekly:
            return jpy(entry.snapshot?.weekly?.pnl_jpy_sum).replacingOccurrences(of: "¥", with: "")
        case .auto, .account:
            return entry.tradeText.contains("ON") ? "ON" : "OFF"
        }
    }

    private var lockFootText: String {
        switch effectiveMode {
        case .shadow:
            return entry.snapshot?.drift?.status == "INSUFFICIENT" ? "WAIT" : "OK"
        case .daily:
            return "D"
        case .weekly:
            return "W"
        case .auto, .account:
            return entry.runnerText.contains("稼働") ? "LIVE" : "STOP"
        }
    }

    private var lockRectDetail: String {
        "D \(jpy(entry.snapshot?.goal?.pnl_jpy)) ・ W \(jpy(entry.snapshot?.weekly?.pnl_jpy_sum)) ・ SH \(entry.snapshot?.drift?.remaining_samples ?? 0)"
    }

    private var ringCaption: String {
        switch effectiveMode {
        case .auto, .account:
            return entry.level
        case .shadow:
            return entry.snapshot?.drift?.status ?? entry.level
        case .daily:
            return jpy(entry.snapshot?.goal?.remaining_jpy)
        case .weekly:
            return pct(entry.snapshot?.weekly?.win_rate_pct)
        }
    }

    private var circularValue: String {
        switch effectiveMode {
        case .auto, .account:
            return entry.tradeText.contains("ON") ? "ON" : "OFF"
        case .shadow:
            return "\(entry.snapshot?.drift?.remaining_samples ?? 0)"
        case .daily:
            return jpy(entry.snapshot?.goal?.pnl_jpy).replacingOccurrences(of: "¥", with: "")
        case .weekly:
            return pct(entry.snapshot?.weekly?.win_rate_pct, digits: 0)
        }
    }

    private var modeColor: Color {
        switch effectiveMode {
        case .auto, .account:
            return levelColor
        case .shadow:
            return (entry.snapshot?.drift?.status == "INSUFFICIENT") ? .orange : levelColor
        case .daily:
            return (entry.snapshot?.goal?.remaining_jpy ?? 1) <= 0 ? .green : .blue
        case .weekly:
            return (entry.snapshot?.weekly?.pnl_jpy_sum ?? 0) >= 0 ? .green : .orange
        }
    }

    private var ringProgress: Double {
        switch effectiveMode {
        case .auto, .account:
            return weeklyProgress
        case .shadow:
            let remain = Double(entry.snapshot?.drift?.remaining_samples ?? 0)
            return max(0.08, min(1, 1 - remain / 10.0))
        case .daily:
            let pnl = entry.snapshot?.goal?.pnl_jpy ?? 0
            let goal = max(1, entry.snapshot?.goal?.goal_jpy ?? 100)
            return max(0.06, min(1, pnl / goal))
        case .weekly:
            return weeklyProgress
        }
    }

    private var weeklyProgress: Double {
        let wr = entry.snapshot?.weekly?.win_rate_pct ?? 0
        return max(0.08, min(1, wr / 100.0))
    }

    private func jpy(_ value: Double?) -> String {
        let n = value ?? 0
        let absValue = abs(n)
        let sign = n < 0 ? "-" : ""
        if absValue >= 10000 {
            return "\(sign)¥\((absValue / 10000).formatted(.number.precision(.fractionLength(1))))万"
        }
        return "\(sign)¥\(Int(absValue.rounded()).formatted())"
    }

    private func jpyOrPending(_ value: Double?) -> String {
        guard let value else { return "未取得" }
        return jpy(value)
    }

    private func pct(_ value: Double?, digits: Int = 1) -> String {
        let n = value ?? 0
        return "\(n.formatted(.number.precision(.fractionLength(digits))))%"
    }
}

struct OuroborosWidgetNativeWidget: Widget {
    let kind = "OuroborosWidgetNativeWidget"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: kind, intent: OuroborosWidgetConfigurationIntent.self, provider: OuroborosWidgetProvider()) { entry in
            OuroborosWidgetView(entry: entry)
                .containerBackground(.clear, for: .widget)
        }
        .configurationDisplayName("Ouroboros")
        .description("口座・Bot・シャドウ状態をホーム画面/ロック画面で確認します。")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryCircular, .accessoryRectangular, .accessoryInline])
        .contentMarginsDisabled()
    }
}

struct OuroborosLiveActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: OuroborosLiveActivityAttributes.self) { context in
            LiveActivityLockView(state: context.state)
                .activityBackgroundTint(Color(red: 0.08, green: 0.09, blue: 0.13))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(context.state.stage)
                            .font(.caption2.weight(.black))
                            .foregroundStyle(.secondary)
                        Text(context.state.balanceText)
                            .font(.headline.weight(.black))
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(context.state.level)
                            .font(.caption2.weight(.black))
                            .foregroundStyle(activityTone(context.state.level))
                        Text(context.state.weeklyText)
                            .font(.headline.weight(.black))
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack {
                        Text(context.state.tradeText)
                        Text("·")
                        Text(context.state.runnerText)
                        Text("·")
                        Text(context.state.shadowText)
                    }
                    .font(.caption.weight(.bold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                }
            } compactLeading: {
                Text(context.state.tradeText.contains("ON") ? "ON" : "OFF")
                    .font(.caption2.weight(.black))
                    .foregroundStyle(activityTone(context.state.level))
            } compactTrailing: {
                Text(context.state.weeklyText)
                    .font(.caption2.weight(.black))
                    .minimumScaleFactor(0.65)
            } minimal: {
                Circle()
                    .fill(activityTone(context.state.level))
            }
        }
    }
}

private struct LiveActivityLockView: View {
    let state: OuroborosLiveActivityAttributes.ContentState

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .stroke(.white.opacity(0.18), lineWidth: 9)
                Circle()
                    .trim(from: 0, to: state.runnerText.contains("稼働") ? 0.82 : 0.28)
                    .stroke(activityTone(state.level), style: StrokeStyle(lineWidth: 9, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                VStack(spacing: 0) {
                    Text("RUN")
                        .font(.caption2.weight(.black))
                        .foregroundStyle(.secondary)
                    Text(state.tradeText.contains("ON") ? "ON" : "OFF")
                        .font(.headline.weight(.black))
                }
            }
            .frame(width: 62, height: 62)
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text("Ouroboros Live")
                        .font(.caption.weight(.black))
                        .tracking(1.1)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(state.level)
                        .font(.caption.weight(.black))
                        .foregroundStyle(activityTone(state.level))
                }
                Text(state.balanceText)
                    .font(.system(size: 28, weight: .black, design: .rounded))
                    .lineLimit(1)
                    .minimumScaleFactor(0.55)
                HStack(spacing: 8) {
                    livePill("DAY", state.dailyText)
                    livePill("WEEK", state.weeklyText)
                    livePill("SH", state.shadowText)
                }
                Text("更新 \(state.updatedAt)")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
    }

    private func livePill(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.system(size: 8, weight: .black))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.weight(.black))
                .lineLimit(1)
                .minimumScaleFactor(0.65)
        }
        .padding(.vertical, 6)
        .padding(.horizontal, 8)
        .background(.white.opacity(0.10), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private func activityTone(_ level: String) -> Color {
    switch level {
    case "ALERT":
        return .red
    case "WARN", "WATCH":
        return .orange
    default:
        return .green
    }
}

@main
struct OuroborosWidgetNativeWidgetBundle: WidgetBundle {
    var body: some Widget {
        OuroborosWidgetNativeWidget()
        OuroborosLiveActivityWidget()
    }
}
