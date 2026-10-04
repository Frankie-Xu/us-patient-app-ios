import Foundation
import PatientAppDomain

public enum CreationFailure: Equatable, Sendable {
    case invalidInput, signInRequired, accessDenied, conflict, unsupported, invalidResponse, unavailable

    public var canRetry: Bool { self == .unavailable }

    public var message: String {
        switch self {
        case .invalidInput: "Enter a title before saving."
        case .signInRequired: "Sign in before saving this item."
        case .accessDenied: "You do not have permission to save this item."
        case .conflict: "The item changed. Check it before submitting again."
        case .unsupported: "Saving this item is unavailable with the current service."
        case .invalidResponse: "The service returned an unsupported item."
        case .unavailable: "This item could not be saved. Try again."
        }
    }

    init(error: any Error) {
        switch error {
        case PatientAppError.invalidInput, PatientAPIClientError.invalidRequest, PatientAPIClientError.validation: self = .invalidInput
        case PatientAPIClientError.unauthorized, PatientAPIClientError.missingBearerToken: self = .signInRequired
        case PatientAPIClientError.forbidden: self = .accessDenied
        case PatientAPIClientError.versionConflict, PatientAppError.versionConflict: self = .conflict
        case PatientAPIClientError.unsupported: self = .unsupported
        case PatientAPIClientError.decoding, PatientAppError.invalidContractData: self = .invalidResponse
        default: self = .unavailable
        }
    }
}

public enum CreationState<Value: Equatable & Sendable>: Equatable, Sendable {
    case empty
    case creating(previous: [Value])
    case saved([Value])
    case failed(CreationFailure, previous: [Value])

    public var items: [Value] {
        switch self {
        case .empty: []
        case let .creating(previous), let .failed(_, previous): previous
        case let .saved(items): items
        }
    }

    public var isCreating: Bool { if case .creating = self { true } else { false } }
    public var failure: CreationFailure? { if case let .failed(error, _) = self { error } else { nil } }
}

/// The frozen contract exposes create operations only. These lists contain items
/// returned by the service during this session; loading account history is separate.
@MainActor
public final class VisitPreparationModel: ObservableObject {
    @Published public private(set) var visitState: CreationState<Visit> = .empty
    @Published public private(set) var taskState: CreationState<PatientAppDomain.Task> = .empty

    private let useCase: VisitPreparationUseCase
    private var pendingVisit: VisitCreateRequest?
    private var pendingTask: TaskCreateRequest?

    public init(client: any PatientAPIClient) { useCase = VisitPreparationUseCase(client: client) }

    public func createVisit(_ request: VisitCreateRequest) async {
        guard !visitState.isCreating else { return }
        let stableRequest = VisitCreateRequest(title: request.title, startsAt: request.startsAt, topicIDs: request.topicIDs, idempotencyKey: request.idempotencyKey ?? UUID().uuidString)
        pendingVisit = stableRequest
        await saveVisit(stableRequest)
    }

    public func retryVisit() async {
        guard visitState.failure?.canRetry == true, let pendingVisit else { return }
        await saveVisit(pendingVisit)
    }

    public func createTask(_ request: TaskCreateRequest) async {
        guard !taskState.isCreating else { return }
        let stableRequest = TaskCreateRequest(title: request.title, visitID: request.visitID, dueAt: request.dueAt, idempotencyKey: request.idempotencyKey ?? UUID().uuidString)
        pendingTask = stableRequest
        await saveTask(stableRequest)
    }

    public func retryTask() async {
        guard taskState.failure?.canRetry == true, let pendingTask else { return }
        await saveTask(pendingTask)
    }

    private func saveVisit(_ request: VisitCreateRequest) async {
        let previous = visitState.items
        visitState = .creating(previous: previous)
        do {
            let visit = try await useCase.createVisit(request)
            visitState = .saved(previous.filter { $0.id != visit.id } + [visit])
            pendingVisit = nil
        } catch {
            visitState = .failed(CreationFailure(error: error), previous: previous)
        }
    }

    private func saveTask(_ request: TaskCreateRequest) async {
        let previous = taskState.items
        taskState = .creating(previous: previous)
        do {
            let task = try await useCase.createTask(request)
            taskState = .saved(previous.filter { $0.id != task.id } + [task])
            pendingTask = nil
        } catch {
            taskState = .failed(CreationFailure(error: error), previous: previous)
        }
    }
}
