# Matching Fx registration inventory

Generated from `service/matching/fx.go` with `python3 architecture-review/generate.py`.
These are registrations in the service module; they are not resolved constructor edges.

## Included modules

- `resource.Module`
- `workerdeployment.Module`

## Providers

- `ConfigProvider`
- `PersistenceRateLimitingParamsProvider`
- `ThrottledLoggerRpsFnProvider`
- `ServiceErrorInterceptorProvider`
- `ContextMetadataInterceptorProvider`
- `RetryableInterceptorProvider`
- `ErrorHandlerProvider`
- `TelemetryInterceptorProvider`
- `NamespaceRateLimitInterceptorProvider`
- `RateLimitInterceptorProvider`
- `VisibilityManagerProvider`
- `WorkersRegistryProvider`
- `NewHandler`
- `service.GrpcServerOptionsProvider`
- `NamespaceReplicationQueueProvider`
- `ServiceResolverProvider`
- `ServerProvider`
- `NewService`
- `simplePartitionScalerFactoryProvider`
- `taskQueueRateLimitFractionProviderProvider`

## Invokes

- `ServiceLifetimeHooks`
