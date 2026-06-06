import ActivityKit
import Foundation

struct OuroborosLiveActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        var level: String
        var stage: String
        var tradeText: String
        var runnerText: String
        var balanceText: String
        var dailyText: String
        var weeklyText: String
        var shadowText: String
        var updatedAt: String
    }

    var name: String
}
