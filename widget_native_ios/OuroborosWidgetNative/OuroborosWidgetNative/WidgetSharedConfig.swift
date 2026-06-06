import Foundation

enum OuroborosWidgetSharedConfig {
    static let appGroupID = "group.com.ouroboros.widgetnative"
    static let hostKey = "ouroboros.native.host"
    static let tokenKey = "ouroboros.native.token"

    static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroupID) ?? .standard
    }
}
