import Foundation

public enum FactReviewBlocker: Equatable, Sendable {
    case lowConfidence(Double)
    case missingSource
    case conflict
}

public enum FactReviewActionState: Equatable, Sendable {
    case needsReview
    case readyToConfirm
    case blocked([FactReviewBlocker])
    case confirmed
    case rejected
}

/// Centralizes the client-side guardrails for explicit fact review. A server
/// response can still reject a stale version; this policy prevents an
/// unsafe automatic confirmation before that request is sent.
public enum FactReviewPolicy {
    public static let defaultMinimumConfidence = 0.80

    public static func blockers(
        for fact: Fact,
        conflictDetected: Bool = false,
        minimumConfidence: Double = defaultMinimumConfidence
    ) -> [FactReviewBlocker] {
        var result: [FactReviewBlocker] = []
        if let confidence = fact.confidence, confidence < minimumConfidence {
            result.append(.lowConfidence(confidence))
        }
        if !fact.isTraceable {
            result.append(.missingSource)
        }
        if conflictDetected {
            result.append(.conflict)
        }
        return result
    }

    public static func actionState(for fact: Fact, conflictDetected: Bool = false) -> FactReviewActionState {
        switch fact.reviewStatus {
        case .confirmed where fact.state == .confirmed:
            return .confirmed
        case .rejected:
            return .rejected
        default:
            let blockers = blockers(for: fact, conflictDetected: conflictDetected)
            guard fact.state == .needsReview else { return .blocked(blockers) }
            return blockers.isEmpty ? .readyToConfirm : .blocked(blockers)
        }
    }

    public static func validateExplicitConfirmation(_ fact: Fact, conflictDetected: Bool = false) throws {
        guard fact.state == .needsReview else {
            throw PatientAppError.reviewRequired
        }
        let blockers = blockers(for: fact, conflictDetected: conflictDetected)
        if blockers.contains(where: {
            if case .missingSource = $0 { return true }
            return false
        }) {
            throw PatientAppError.sourceRequired
        }
        guard blockers.isEmpty else {
            throw PatientAppError.reviewRequired
        }
        guard !fact.wasExplicitlyReviewed else {
            throw PatientAppError.reviewRequired
        }
    }
}
