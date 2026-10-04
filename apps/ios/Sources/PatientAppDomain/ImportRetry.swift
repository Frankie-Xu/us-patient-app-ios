import Foundation

public protocol ImportClock: Sendable {
    var now: Date { get }
    func sleep(for duration: Duration) async throws
}

public struct SystemImportClock: ImportClock, Sendable {
    public init() {}

    public var now: Date { Date() }

    public func sleep(for duration: Duration) async throws {
        try await _Concurrency.Task.sleep(for: duration)
    }
}

public struct ImportRetryPolicy: Equatable, Sendable {
    public let maxAttempts: Int
    public let maxDuration: Duration
    public let initialDelay: Duration
    public let maximumDelay: Duration

    public init(maxAttempts: Int = 6, maxDuration: Duration = .seconds(30), initialDelay: Duration = .milliseconds(250), maximumDelay: Duration = .seconds(4)) {
        self.maxAttempts = max(1, maxAttempts)
        self.maxDuration = maxDuration
        self.initialDelay = max(.zero, initialDelay)
        self.maximumDelay = max(self.initialDelay, maximumDelay)
    }

    public func delay(forRetry retry: Int) -> Duration {
        guard retry > 0 else { return .zero }
        let initialNanoseconds = nanoseconds(initialDelay)
        let maximumNanoseconds = nanoseconds(maximumDelay)
        let shift = min(retry - 1, 62)
        let multiplier = Int64(1) << Int64(shift)
        let (scaled, overflow) = initialNanoseconds.multipliedReportingOverflow(by: multiplier)
        let bounded = overflow ? maximumNanoseconds : min(scaled, maximumNanoseconds)
        return .nanoseconds(bounded)
    }

    private func nanoseconds(_ duration: Duration) -> Int64 {
        let components = duration.components
        let seconds = components.seconds.multipliedReportingOverflow(by: 1_000_000_000)
        if seconds.overflow { return Int64.max }
        let attoseconds = components.attoseconds / 1_000_000_000
        let sum = seconds.partialValue.addingReportingOverflow(attoseconds)
        return sum.overflow ? Int64.max : max(0, sum.partialValue)
    }
}
