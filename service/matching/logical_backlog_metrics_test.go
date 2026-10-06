package matching

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	deploymentpb "go.temporal.io/api/deployment/v1"
	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	taskqueuepb "go.temporal.io/api/taskqueue/v1"
	"go.temporal.io/server/common/future"
	"go.temporal.io/server/common/log/tag"
	"go.temporal.io/server/common/metrics/metricstest"
	"go.temporal.io/server/common/testing/testlogger"
	"go.temporal.io/server/common/worker_versioning"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/types/known/durationpb"
)

func TestLogicalBacklogMetrics_BuildIDBreakdownDisabledAfterEmit(t *testing.T) {
	t.Parallel()
	for _, onStop := range []bool{false, true} {
		t.Run(fmt.Sprintf("onStop=%t", onStop), func(t *testing.T) {
			t.Parallel()
			pm, capture, userData := newLogicalBacklogMetricsTestManager(t)
			userData.EXPECT().GetUserData().Return(nil, nil, nil).AnyTimes()
			versioned := NewMockphysicalTaskQueueManager(gomock.NewController(t))
			versioned.EXPECT().WaitUntilInitialized(gomock.Any()).Return(nil).AnyTimes()
			versioned.EXPECT().GetStatsByPriority(true).Return(map[int32]*taskqueuepb.TaskQueueStats{
				1: {ApproximateBacklogCount: 7, ApproximateBacklogAge: durationpb.New(time.Second)},
			}).AnyTimes()
			pm.versionedQueues = map[PhysicalTaskQueueVersion]physicalTaskQueueManager{
				{buildId: "A", deploymentSeriesName: "foo"}: versioned,
			}
			previous, err := pm.fetchAndEmitLogicalBacklogMetrics(t.Context())
			require.NoError(t, err)
			versionTag := worker_versioning.ExternalWorkerDeploymentVersionToString(
				&deploymentpb.WorkerDeploymentVersion{DeploymentName: "foo", BuildId: "A"},
			)
			count, found := latestLogicalBacklogCount(capture.Snapshot(), versionTag, "1")
			require.True(t, found)
			require.InDelta(t, 7, count, 0.001)

			pm.config.BreakdownMetricsByBuildID = func() bool { return false }
			if onStop {
				pm.emitZeroLogicalBacklog(previous)
			} else {
				current, err := pm.fetchAndEmitLogicalBacklogMetrics(t.Context())
				require.NoError(t, err)
				require.NotContains(t, current, versionTag)
				pm.emitZeroLogicalBacklog(staleLogicalBacklog(previous, current))
			}
			count, found = latestLogicalBacklogCount(capture.Snapshot(), versionTag, "1")
			require.True(t, found)
			require.Zero(t, count)
			age, found := latestLogicalBacklogAge(capture.Snapshot(), versionTag, "1")
			require.True(t, found)
			require.Zero(t, age)
			require.Empty(t, latestLogicalBacklogCountsByPriority(capture.Snapshot(), "__versioned__"))
		})
	}
}

func TestLogicalBacklogMetrics_EmitError(t *testing.T) {
	t.Parallel()
	for _, tc := range []struct {
		name     string
		err      error
		wantLogs int64
	}{
		{name: "unexpected", err: errors.New("describe failed"), wantLogs: 1},
		{name: "canceled", err: context.Canceled},
		{name: "service canceled", err: serviceerror.NewCanceled("closing")},
		{name: "queue closed", err: fmt.Errorf("user data: %w", errTaskQueueClosed)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			pm, capture, userData := newLogicalBacklogMetricsTestManager(t)
			logger := testlogger.NewTestLogger(t, testlogger.FailOnAnyUnexpectedError)
			pm.logger = logger
			logged := logger.Expect(testlogger.Error, "failed to emit logical backlog metrics", tag.Error(tc.err))
			ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
			defer cancel()
			failureProcessed := make(chan struct{})
			gomock.InOrder(
				userData.EXPECT().GetUserData().Return(nil, nil, nil),
				userData.EXPECT().GetUserData().Return(nil, nil, tc.err),
				userData.EXPECT().GetUserData().Do(func() {
					close(failureProcessed)
					<-ctx.Done()
				}).Return(nil, nil, context.Canceled),
			)
			done := make(chan error, 1)
			go func() { done <- pm.emitLogicalBacklogMetrics(ctx) }()
			select {
			case <-failureProcessed:
			case <-ctx.Done():
				t.Fatal("emitter did not retry after the failed describe")
			}

			count, found := latestLogicalBacklogCount(capture.Snapshot(), "__unversioned__", "1")
			require.True(t, found)
			require.InDelta(t, 5, count, 0.001)
			require.Equal(t, tc.wantLogs, logged.MatchCount())

			cancel()
			select {
			case err := <-done:
				require.ErrorIs(t, err, context.Canceled)
			case <-time.After(5 * time.Second):
				t.Fatal("emitter did not stop")
			}
			count, found = latestLogicalBacklogCount(capture.Snapshot(), "__unversioned__", "1")
			require.True(t, found)
			require.Zero(t, count)
			age, found := latestLogicalBacklogAge(capture.Snapshot(), "__unversioned__", "1")
			require.True(t, found)
			require.Zero(t, age)
		})
	}
}

func TestLogicalBacklogMetrics_Disabled(t *testing.T) {
	t.Parallel()
	for _, byPartition := range []bool{false, true} {
		t.Run(fmt.Sprintf("byPartition=%t", byPartition), func(t *testing.T) {
			t.Parallel()
			pm, _, _ := newLogicalBacklogMetricsTestManager(t)
			if byPartition {
				pm.config.BreakdownMetricsByPartition = func() bool { return false }
			} else {
				pm.config.BreakdownMetricsByTaskQueue = func() bool { return false }
			}
			versions, err := pm.fetchAndEmitLogicalBacklogMetrics(t.Context())
			require.NoError(t, err)
			require.Nil(t, versions)
		})
	}
}

func newLogicalBacklogMetricsTestManager(t *testing.T) (*taskQueuePartitionManagerImpl, *metricstest.Capture, *MockuserDataManager) {
	t.Helper()
	ctrl := gomock.NewController(t)
	partition := newRootPartition(namespaceID, taskQueueName, enumspb.TASK_QUEUE_TYPE_WORKFLOW)
	queue := NewMockphysicalTaskQueueManager(ctrl)
	queue.EXPECT().QueueKey().Return(UnversionedQueueKey(partition)).AnyTimes()
	queue.EXPECT().GetStatsByPriority(true).Return(map[int32]*taskqueuepb.TaskQueueStats{
		1: {ApproximateBacklogCount: 5, ApproximateBacklogAge: durationpb.New(time.Second)},
	}).AnyTimes()
	ready := future.NewFuture[physicalTaskQueueManager]()
	ready.Set(queue, nil)
	userData := NewMockuserDataManager(ctrl)
	userData.EXPECT().PartitionScale().Return(nil).AnyTimes()
	handler := metricstest.NewCaptureHandler()
	capture := handler.StartCapture()
	t.Cleanup(func() { handler.StopCapture(capture) })
	pm := &taskQueuePartitionManagerImpl{
		partition:          partition,
		defaultQueueFuture: ready,
		userDataManager:    userData,
		metricsHandler:     handler,
		logger:             testlogger.NewTestLogger(t, testlogger.FailOnAnyUnexpectedError),
		config: &taskQueueConfig{
			BreakdownMetricsByTaskQueue: func() bool { return true },
			BreakdownMetricsByPartition: func() bool { return true },
			BreakdownMetricsByBuildID:   func() bool { return true },
			BacklogMetricsEmitInterval:  func() time.Duration { return time.Millisecond },
		},
	}
	return pm, capture, userData
}
