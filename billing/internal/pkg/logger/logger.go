package logger

import (
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// Logger wraps the standard library's log.Logger to provide
// dual output (stdout + rotating file) with automatic daily rotation.
type Logger struct {
	*log.Logger
	mu       sync.Mutex
	file     *os.File
	writer   io.Writer // the combined multi-writer (stdout + file)
	logDir   string
	logName  string
	lastDate string
}

// Config holds logger configuration.
type Config struct {
	LogDir  string // directory for log files (default "./log")
	LogName string // log file name prefix (default "auth")
}

// New creates a new Logger that writes to both stdout and a local file.
// The file rotates daily — a new file is opened when the date changes.
func New(cfg Config) (*Logger, error) {
	if cfg.LogDir == "" {
		cfg.LogDir = "log"
	}
	if cfg.LogName == "" {
		cfg.LogName = "auth"
	}

	if err := os.MkdirAll(cfg.LogDir, 0o755); err != nil {
		return nil, fmt.Errorf("create log dir: %w", err)
	}

	l := &Logger{
		logDir:  cfg.LogDir,
		logName: cfg.LogName,
	}

	if err := l.openLogFile(); err != nil {
		return nil, err
	}

	// Write to both stdout and the log file.
	l.writer = io.MultiWriter(os.Stdout, l.file)
	l.Logger = log.New(l.writer, "", log.LstdFlags)

	return l, nil
}

// openLogFile opens today's log file. Called on startup and on rotation.
func (l *Logger) openLogFile() error {
	if l.file != nil {
		l.file.Close()
	}

	today := time.Now().UTC().Format("2006-01-02")
	filename := filepath.Join(l.logDir, fmt.Sprintf("%s-%s.log", l.logName, today))

	f, err := os.OpenFile(filename, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return fmt.Errorf("open log file: %w", err)
	}

	l.file = f
	l.lastDate = today
	return nil
}

// Rotate checks if the date has changed and rotates the log file if needed.
// Call this periodically (e.g., every minute) from a background goroutine.
func (l *Logger) Rotate() {
	l.mu.Lock()
	defer l.mu.Unlock()

	today := time.Now().UTC().Format("2006-01-02")
	if today != l.lastDate {
		if err := l.openLogFile(); err != nil {
			log.Printf("ERROR: failed to rotate log file: %v", err)
			return
		}
		// Update the multi-writer to use the new file.
		l.writer = io.MultiWriter(os.Stdout, l.file)
		l.Logger.SetOutput(l.writer)

		// Clean up old log files (keep 30 days).
		l.cleanOldLogs(30)
	}
}

// cleanOldLogs removes log files older than maxDays.
func (l *Logger) cleanOldLogs(maxDays int) {
	cutoff := time.Now().UTC().AddDate(0, 0, -maxDays)

	entries, err := os.ReadDir(l.logDir)
	if err != nil {
		return
	}

	prefix := l.logName + "-"
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if len(name) < len(prefix)+11 { // prefix + "YYYY-MM-DD" + ".log"
			continue
		}
		if name[:len(prefix)] != prefix {
			continue
		}
		dateStr := name[len(prefix) : len(prefix)+10]
		t, err := time.Parse("2006-01-02", dateStr)
		if err != nil {
			continue
		}
		if t.Before(cutoff) {
			os.Remove(filepath.Join(l.logDir, name))
		}
	}
}

// Writer returns the underlying io.Writer (stdout + rotating file).
// Use this for log.SetOutput() or gin.DefaultWriter.
func (l *Logger) Writer() io.Writer {
	return l.writer
}

// Close closes the log file.
func (l *Logger) Close() error {
	if l.file != nil {
		return l.file.Close()
	}
	return nil
}

// StartRotation starts a background goroutine that rotates the log file
// every minute when the date changes.
func (l *Logger) StartRotation() {
	go func() {
		for {
			time.Sleep(1 * time.Minute)
			l.Rotate()
		}
	}()
}
