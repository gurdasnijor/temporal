package matching

// Engine shutdown with many loaded partitions, before and after MTC-1034. Not part of the PR.
// Needs partition_lifecycle_bench_test.go (newBenchEngine, loadBenchPartition).

import (
	"fmt"
	"runtime"
	"sync"
	"testing"
	"time"
)

// Loads n partitions, then times engine Stop. Also reports goroutines still running a second after
// Stop beyond those running before the engine was created.
func BenchmarkEngineStop(b *testing.B) {
	for _, n := range []int{1000, 10000} {
		for _, delay := range benchDBDelays {
			b.Run(fmt.Sprintf("partitions=%d/dbDelay=%v", n, delay), func(b *testing.B) {
				var leaked int
				for i := 0; i < b.N; i++ {
					b.StopTimer()
					before := runtime.NumGoroutine()
					e := newBenchEngine(b, delay)
					var wg sync.WaitGroup
					sem := make(chan struct{}, 64)
					for p := range n {
						sem <- struct{}{}
						wg.Go(func() {
							defer func() { <-sem }()
							loadBenchPartition(b, e, fmt.Sprintf("tq-%d-%d", i, p))
						})
					}
					wg.Wait()
					b.StartTimer()
					e.Stop()
					b.StopTimer()
					time.Sleep(time.Second) // nolint:forbidigo
					leaked = max(leaked, runtime.NumGoroutine()-before)
				}
				b.ReportMetric(float64(leaked), "goroutines-left")
			})
		}
	}
}
