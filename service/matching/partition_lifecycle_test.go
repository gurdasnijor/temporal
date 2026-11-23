package matching

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/require"
	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/server/common/namespace"
	"go.uber.org/mock/gomock"
)

// Partitions loaded by these tests use their own namespace ID, so that the engine's loaded counts for it
// start at zero even when another partition manager shares the engine.
const lifecycleNamespaceID = "lifecycle-ns-id"

// loadedCounts returns the engine's non-zero loaded partition and physical queue counts for nsID. Once
// everything it loaded has stopped, it's empty: a partition or queue that started and never stopped
// leaves a positive count, and one stopped twice a negative one.
func loadedCounts(e *matchingEngineImpl, nsID string) map[string]int {
	e.gaugeMetrics.lock.Lock()
	defer e.gaugeMetrics.lock.Unlock()
	counts := make(map[string]int)
	for k, v := range e.gaugeMetrics.loadedTaskQueuePartitionCount {
		if k.namespaceID == nsID && v != 0 {
			counts[fmt.Sprintf("partitions %+v", k)] = v
		}
	}
	for k, v := range e.gaugeMetrics.loadedPhysicalTaskQueueCount {
		if k.namespaceID == nsID && v != 0 {
			counts[fmt.Sprintf("physical queues %+v", k)] = v
		}
	}
	return counts
}

// A partition is stopped by whoever removes it from the engine's map, so an unload that comes after
// engine Stop (or races with it) doesn't stop it again.
func TestEngineStop_ConcurrentUnloadStopsOnce(t *testing.T) {
	for range 20 {
		ctrl := gomock.NewController(t)
		e := newFailoverTestEngine(t, ctrl, namespace.NewMockRegistry(ctrl))
		var pms []*MocktaskQueuePartitionManager
		for i := range 100 {
			partition := newRootPartition(namespaceID, fmt.Sprintf("tq-%d", i), enumspb.TASK_QUEUE_TYPE_WORKFLOW)
			pm := NewMocktaskQueuePartitionManager(ctrl)
			pm.EXPECT().Partition().Return(partition).AnyTimes()
			pm.EXPECT().Stop(gomock.Any()) // exactly once
			e.updateTaskQueue(partition, pm)
			pms = append(pms, pm)
		}

		start := make(chan struct{})
		var wg sync.WaitGroup
		for _, pm := range pms {
			wg.Go(func() {
				<-start
				e.unloadTaskQueuePartition(pm, unloadCauseIdle)
			})
		}
		wg.Go(func() {
			<-start
			e.Stop()
		})
		close(start)
		wg.Wait()

		// Unloads that arrive after Stop find nothing to stop.
		for _, pm := range pms {
			e.unloadTaskQueuePartition(pm, unloadCauseIdle)
		}
		require.Empty(t, e.getTaskQueuePartitions(1000))
	}
}

// Engine Stop waits for an unload that removed a partition before Stop took the map.
func TestEngineStop_WaitsForUnloadInProgress(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctrl := gomock.NewController(t)
		e := newFailoverTestEngine(t, ctrl, namespace.NewMockRegistry(ctrl))

		partition := newRootPartition(namespaceID, taskQueueName, enumspb.TASK_QUEUE_TYPE_WORKFLOW)
		release := make(chan struct{})
		pm := NewMocktaskQueuePartitionManager(ctrl)
		pm.EXPECT().Partition().Return(partition).AnyTimes()
		pm.EXPECT().Stop(unloadCauseIdle).Do(func(unloadCause) { <-release })
		e.updateTaskQueue(partition, pm)
		go e.unloadTaskQueuePartition(pm, unloadCauseIdle)
		synctest.Wait()

		var engineStopped atomic.Bool
		go func() {
			e.Stop()
			engineStopped.Store(true)
		}()
		synctest.Wait()
		stoppedBeforeRelease := engineStopped.Load()

		close(release)
		synctest.Wait()
		require.False(t, stoppedBeforeRelease)
		require.True(t, engineStopped.Load())
	})
}

func TestGetTaskQueuePartitionManager_AfterEngineStop(t *testing.T) {
	ctrl := gomock.NewController(t)
	_, registry := createMockNamespaceCache(ctrl, namespaceName)
	e := newFailoverTestEngine(t, ctrl, registry)
	e.Stop()

	partition := newRootPartition(lifecycleNamespaceID, taskQueueName, enumspb.TASK_QUEUE_TYPE_WORKFLOW)
	pm, _, err := e.getTaskQueuePartitionManager(t.Context(), partition, true, loadCausePoll)
	require.ErrorIs(t, err, errTaskQueueClosed)
	require.Nil(t, pm)
	require.Empty(t, e.getTaskQueuePartitions(10))
	require.Empty(t, loadedCounts(e, lifecycleNamespaceID))
}

// Loads and unloads real partitions while the engine shuts down. Every partition that started is
// stopped exactly once, and none is left in the map.
func TestEngineStop_ConcurrentLoadAndUnload(t *testing.T) {
	for range 5 {
		ctrl := gomock.NewController(t)
		_, registry := createMockNamespaceCache(ctrl, namespaceName)
		e := newFailoverTestEngine(t, ctrl, registry)

		ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
		start := make(chan struct{})
		var wg sync.WaitGroup
		for i := range 50 {
			wg.Go(func() {
				<-start
				partition := newRootPartition(lifecycleNamespaceID, fmt.Sprintf("tq-%d", i), enumspb.TASK_QUEUE_TYPE_WORKFLOW)
				pm, _, err := e.getTaskQueuePartitionManager(ctx, partition, true, loadCausePoll)
				if err == nil && i%2 == 0 {
					e.unloadTaskQueuePartition(pm, unloadCauseIdle)
				}
			})
		}
		wg.Go(func() {
			<-start
			e.Stop()
		})
		close(start)
		wg.Wait()
		cancel()

		require.Empty(t, e.getTaskQueuePartitions(1000))
		require.Empty(t, loadedCounts(e, lifecycleNamespaceID))
	}
}
