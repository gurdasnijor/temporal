package main

import (
	"encoding/base64"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	historypb "go.temporal.io/api/history/v1"
	persistencespb "go.temporal.io/server/api/persistence/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func messageFor(kind string) (proto.Message, error) {
	switch kind {
	case "history":
		return &historypb.History{}, nil
	case "history-tree":
		return &persistencespb.HistoryTreeInfo{}, nil
	case "execution-info":
		return &persistencespb.WorkflowExecutionInfo{}, nil
	case "execution-state":
		return &persistencespb.WorkflowExecutionState{}, nil
	case "task-queue":
		return &persistencespb.TaskQueueInfo{}, nil
	case "task":
		return &persistencespb.AllocatedTaskInfo{}, nil
	case "task-queue-user-data":
		return &persistencespb.TaskQueueUserData{}, nil
	case "namespace":
		return &persistencespb.NamespaceDetail{}, nil
	default:
		return nil, fmt.Errorf("unknown blob type %q", kind)
	}
}

func decodeInput(input []byte, format string) ([]byte, error) {
	value := strings.TrimSpace(string(input))
	value = strings.TrimPrefix(value, `\x`)
	value = strings.TrimPrefix(value, "0x")
	value = strings.Join(strings.Fields(value), "")
	if value == "" {
		return nil, errors.New("empty input")
	}
	switch format {
	case "hex":
		return hex.DecodeString(value)
	case "base64":
		return base64.StdEncoding.DecodeString(value)
	default:
		return nil, fmt.Errorf("unsupported input format %q", format)
	}
}

func run() error {
	kind := flag.String("type", "", "history, history-tree, execution-info, execution-state, task-queue, task, task-queue-user-data, or namespace")
	inputPath := flag.String("input", "-", "path to a hex/base64 cell export, or - for stdin")
	format := flag.String("format", "hex", "hex or base64")
	flag.Parse()
	message, err := messageFor(*kind)
	if err != nil {
		return err
	}
	var input []byte
	if *inputPath == "-" {
		input, err = io.ReadAll(os.Stdin)
	} else {
		input, err = os.ReadFile(*inputPath)
	}
	if err != nil {
		return fmt.Errorf("read input: %w", err)
	}
	data, err := decodeInput(input, *format)
	if err != nil {
		return fmt.Errorf("decode %s input: %w", *format, err)
	}
	if err := proto.Unmarshal(data, message); err != nil {
		return fmt.Errorf("decode %s protobuf: %w", *kind, err)
	}
	output, err := (protojson.MarshalOptions{Multiline: true, Indent: "  ", UseProtoNames: true}).Marshal(message)
	if err != nil {
		return fmt.Errorf("render JSON: %w", err)
	}
	_, err = fmt.Fprintln(os.Stdout, string(output))
	return err
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
