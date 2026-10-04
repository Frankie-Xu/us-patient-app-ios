import Foundation
import PatientAppDomain

@MainActor
public final class ImportFlowModel: ObservableObject {
    @Published public private(set) var state: ImportFlowState = .idle

    private let useCase: ImportUseCase
    private var lastRequest: ImportRequest?

    public init(client: any PatientAPIClient) {
        self.useCase = ImportUseCase(client: client)
    }

    public var isBusy: Bool {
        switch state {
        case .uploading, .processing: true
        default: false
        }
    }

    public var error: PatientAppError? {
        guard case let .failed(error) = state else { return nil }
        return error
    }

    public var currentImportTitle: String {
        lastRequest?.title ?? "record"
    }

    public func start(_ request: ImportRequest) async {
        lastRequest = request
        state = .processing
        do {
            let snapshot = try await useCase.run(request) { [weak self] stage in
                await self?.update(stage: stage)
            }
            state = snapshot.facts.isEmpty ? .empty(snapshot) : .reviewRequired(snapshot)
        } catch let error as PatientAppError {
            state = .failed(error)
        } catch {
            state = .failed(.unavailable)
        }
    }

    public func retry() async {
        guard let lastRequest else { return }
        await start(lastRequest)
    }

    public func editFact(_ fact: Fact, value: String) async {
        guard case let .reviewRequired(snapshot) = state else { return }
        do {
            let edited = try await useCase.editFact(FactEditCommand(documentID: snapshot.ticket.documentID, factID: fact.id, value: value))
            update(snapshot: snapshot.replacing(fact: edited))
        } catch let error as PatientAppError {
            state = .failed(error)
        } catch {
            state = .failed(.unavailable)
        }
    }

    public func confirmFact(_ fact: Fact) async {
        guard case let .reviewRequired(snapshot) = state else { return }
        do {
            let confirmed = try await useCase.confirmFact(FactReviewCommand(documentID: snapshot.ticket.documentID, factID: fact.id))
            let updated = snapshot.replacing(fact: confirmed)
            state = updated.facts.contains(where: { $0.state == .needsReview }) ? .reviewRequired(updated) : .completed(updated)
        } catch let error as PatientAppError {
            state = .failed(error)
        } catch {
            state = .failed(.unavailable)
        }
    }

    private func update(stage: ImportStage) {
        switch stage {
        case .uploading: state = .uploading
        case .processing, .loadingFacts: state = .processing
        }
    }

    private func update(snapshot: ImportSnapshot) {
        state = .reviewRequired(snapshot)
    }
}

private extension ImportSnapshot {
    func replacing(fact: Fact) -> ImportSnapshot {
        var copy = self
        copy.facts = copy.facts.map { $0.id == fact.id ? fact : $0 }
        return copy
    }
}
