package matching

// Benchmarks comparing partition load/unload costs before and after MTC-1034. Not part of the PR:
// copied into the tree for main and for the branch, and compared with benchstat. Uses only functions
// that exist on both.

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/server/api/matchingservice/v1"
	"go.temporal.io/server/api/matchingservicemock/v1"
	persistencespb "go.temporal.io/server/api/persistence/v1"
	"go.temporal.io/server/common/log"
	"go.temporal.io/server/common/namespace"
	"go.uber.org/mock/gomock"
)

var benchDBDelays = []time.Duration{0, 2 * time.Millisecond}

// newBenchEngine returns a started engine over the in-memory task manager. dbDelay makes most of its
// calls sleep up to that long, as a stand-in for persistence latency.
func newBenchEngine(b *testing.B, dbDelay time.Duration) *matchingEngineImpl {
	ctrl := gomock.NewController(b)
	_, registry := createMockNamespaceCache(ctrl, namespace.Name(namespaceName))
	client := matchingservicemock.NewMockMatchingServiceClient(ctrl)
	client.EXPECT().ForceLoadTaskQueuePartition(gomock.Any(), gomock.Any(), gomock.Any()).
		Return(&matchingservice.ForceLoadTaskQueuePartitionResponse{}, nil).AnyTimes()
	client.EXPECT().ForceLoadTaskQueuePartition(gomock.Any(), gomock.Any()).
		Return(&matchingservice.ForceLoadTaskQueuePartitionResponse{}, nil).AnyTimes()
	e := createTestMatchingEngine(log.NewNoopLogger(), ctrl, defaultTestConfig(), client, registry)
	e.taskManager.(*testTaskManager).delayInjection = dbDelay
	e.Start()
	b.Cleanup(e.Stop)
	return e
}

func loadBenchPartition(b *testing.B, e *matchingEngineImpl, tq string) *taskQueuePartitionManagerImpl {
	p := newRootPartition(namespaceID, tq, enumspb.TASK_QUEUE_TYPE_WORKFLOW)
	pm, _, err := e.getTaskQueuePartitionManager(context.Background(), p, true, loadCausePoll)
	if err != nil {
		b.Fatal(err)
	}
	return pm.(*taskQueuePartitionManagerImpl)
}

// Load a partition, wait for it to initialize, unload it; in parallel across task queues.
func BenchmarkPartitionLoadUnload(b *testing.B) {
	for _, delay := range benchDBDelays {
		b.Run(fmt.Sprintf("dbDelay=%v", delay), func(b *testing.B) {
			e := newBenchEngine(b, delay)
			var n atomic.Int64
			b.ResetTimer()
			b.RunParallel(func(pb *testing.PB) {
				for pb.Next() {
					pm := loadBenchPartition(b, e, fmt.Sprintf("tq-%d", n.Add(1)))
					e.unloadTaskQueuePartition(pm, unloadCauseIdle)
				}
			})
		})
	}
}

// Unload a partition that has versioned queues with a backlog. Only the unload is timed. Also reports
// the longest a versioned-queue lookup on that partition waited while it stopped.
func BenchmarkPartitionStopWithVersionedBacklog(b *testing.B) {
	const (
		versions = 10
		backlog  = 500
	)
	for _, delay := range benchDBDelays {
		b.Run(fmt.Sprintf("dbDelay=%v", delay), func(b *testing.B) {
			e := newBenchEngine(b, delay)
			var maxLookup time.Duration
			for i := 0; i < b.N; i++ {
				b.StopTimer()
				pm := loadBenchPartition(b, e, fmt.Sprintf("tq-%d", i))
				for v := range versions {
					vq, err := pm.getVersionedQueue(context.Background(), "", fmt.Sprintf("build-%d", v), nil, true)
					if err != nil {
						b.Fatal(err)
					}
					// From 32 goroutines, so the task writer batches them without hitting its
					// outstanding-appends limit.
					var spool sync.WaitGroup
					for w := range 32 {
						spool.Go(func() {
							for t := w; t < backlog; t += 32 {
								if err := vq.SpoolTask(&persistencespb.TaskInfo{
									NamespaceId: namespaceID,
									RunId:       "run",
									WorkflowId:  fmt.Sprintf("wf-%d", t),
								}); err != nil {
									b.Error(err)
								}
							}
						})
					}
					spool.Wait()
				}

				done := make(chan struct{})
				var wg sync.WaitGroup
				wg.Go(func() {
					for {
						select {
						case <-done:
							return
						default:
						}
						start := time.Now()
						_, _ = pm.getVersionedQueueNoWait("", "build-0", nil, false)
						maxLookup = max(maxLookup, time.Since(start))
					}
				})
				b.StartTimer()
				e.unloadTaskQueuePartition(pm, unloadCauseIdle)
				b.StopTimer()
				close(done)
				wg.Wait()
			}
			b.ReportMetric(float64(maxLookup.Microseconds()), "max-lookup-µs")
		})
	}
}

// Look up an existing versioned queue (the hot-path read) while another goroutine keeps creating new
// versioned queues on the same partition, which takes the write lock.
func BenchmarkVersionedQueueLookupWhileCreating(b *testing.B) {
	e := newBenchEngine(b, 0)
	pm := loadBenchPartition(b, e, "tq")
	if _, err := pm.getVersionedQueue(context.Background(), "", "hot", nil, true); err != nil {
		b.Fatal(err)
	}
	done := make(chan struct{})
	var wg sync.WaitGroup
	var created atomic.Int64
	wg.Go(func() {
		for i := 0; ; i++ {
			select {
			case <-done:
				return
			default:
			}
			_, _ = pm.getVersionedQueueNoWait("", fmt.Sprintf("build-%d", i), nil, true)
			created.Add(1)
		}
	})
	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			if vq, _ := pm.getVersionedQueueNoWait("", "hot", nil, false); vq == nil {
				b.Error("hot queue missing")
			}
		}
	})
	b.StopTimer()
	close(done)
	wg.Wait()
	b.ReportMetric(float64(created.Load())/b.Elapsed().Seconds(), "creates/s")
	e.unloadTaskQueuePartition(pm, unloadCauseIdle)
}
