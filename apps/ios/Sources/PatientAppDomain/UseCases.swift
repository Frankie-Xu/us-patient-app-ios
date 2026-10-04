import Foundation

public protocol PatientRepository: Sendable {
    associatedtype Value: Sendable
    func load() async throws -> Value
}

public struct EmptyPatientRepository<Value: Sendable>: PatientRepository {
    public init() {}

    public func load() async throws -> Value {
        throw PatientAppError.unavailable
    }
}
