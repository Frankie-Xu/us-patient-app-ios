import Foundation
import PatientAppDomain

public struct FactReviewPresentation: Equatable, Sendable, Identifiable {
    public let id: UUID
    public let fact: Fact
    public let actionState: FactReviewActionState
    public let blockers: [FactReviewBlocker]
    public let confidenceLabel: String
    public let sourceLocation: DocumentSourceLocation?

    public init(fact: Fact, conflictDetected: Bool = false) {
        self.id = fact.id
        self.fact = fact
        self.actionState = FactReviewPolicy.actionState(for: fact, conflictDetected: conflictDetected)
        self.blockers = FactReviewPolicy.blockers(for: fact, conflictDetected: conflictDetected)
        if let confidence = fact.confidence {
            self.confidenceLabel = String(format: "%.0f%% confidence", confidence * 100)
        } else {
            self.confidenceLabel = "Confidence unavailable"
        }
        self.sourceLocation = DocumentSourceLocation.from(fact: fact)
    }

    public var canConfirm: Bool {
        actionState == .readyToConfirm
    }

    public var isAutomaticallyConfirmable: Bool {
        false
    }
}

@MainActor
public final class FactReviewModel: ObservableObject {
    @Published public private(set) var facts: [Fact]
    @Published public private(set) var conflictFactIDs: Set<UUID>

    public init(facts: [Fact] = [], conflictFactIDs: Set<UUID> = []) {
        self.facts = facts
        self.conflictFactIDs = conflictFactIDs
    }

    public var presentations: [FactReviewPresentation] {
        facts.map { FactReviewPresentation(fact: $0, conflictDetected: conflictFactIDs.contains($0.id)) }
    }

    public func update(facts: [Fact]) {
        self.facts = facts
    }

    public func markConflict(for factID: UUID, conflicted: Bool = true) {
        if conflicted {
            conflictFactIDs.insert(factID)
        } else {
            conflictFactIDs.remove(factID)
        }
    }

    public func validateConfirmation(for fact: Fact) throws {
        try FactReviewPolicy.validateExplicitConfirmation(fact, conflictDetected: conflictFactIDs.contains(fact.id))
    }

    public func applyExplicitConfirmation(to fact: Fact) throws -> Fact {
        try validateConfirmation(for: fact)
        var confirmed = fact
        try confirmed.confirmAfterExplicitReview()
        facts = facts.map { $0.id == confirmed.id ? confirmed : $0 }
        return confirmed
    }
}
