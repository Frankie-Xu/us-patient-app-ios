import Foundation

public struct AccountHistorySnapshot: Codable, Equatable, Hashable, Sendable {
    public let topics: [Topic]
    public let visits: [Visit]
    public let tasks: [Task]

    public init(topics: [Topic] = [], visits: [Visit] = [], tasks: [Task] = []) {
        self.topics = topics
        self.visits = visits
        self.tasks = tasks
    }

    public var isEmpty: Bool { topics.isEmpty && visits.isEmpty && tasks.isEmpty }
}

public protocol AccountHistoryRepository: Sendable {
    func topics() async throws -> [Topic]
    func visits() async throws -> [Visit]
    func tasks() async throws -> [Task]
}

public struct PatientAPIAccountHistoryRepository: AccountHistoryRepository, Sendable {
    private let client: any PatientAPIClient

    public init(client: any PatientAPIClient) { self.client = client }

    public func topics() async throws -> [Topic] { try await client.listTopics() }
    public func visits() async throws -> [Visit] { try await client.listVisits() }
    public func tasks() async throws -> [Task] { try await client.listTasks() }
}

public struct AccountHistoryUseCase: Sendable {
    private let repository: any AccountHistoryRepository

    public init(repository: any AccountHistoryRepository) { self.repository = repository }
    public init(client: any PatientAPIClient) { self.repository = PatientAPIAccountHistoryRepository(client: client) }

    public func load() async throws -> AccountHistorySnapshot {
        async let topics = repository.topics()
        async let visits = repository.visits()
        async let tasks = repository.tasks()
        return try await AccountHistorySnapshot(topics: topics, visits: visits, tasks: tasks)
    }
}
