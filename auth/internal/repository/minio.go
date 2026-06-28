package repository

import (
	"context"
	"log"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"second-brain/auth/internal/pkg/config"
)

// EnsureBuckets creates the MinIO bucket if it doesn't exist.
func EnsureBuckets(cfg *config.Config) error {
	client, err := minio.New(cfg.MinIOEndpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(cfg.MinIOAccessKey, cfg.MinIOSecretKey, ""),
		Secure: false,
	})
	if err != nil {
		return err
	}

	bucketName := cfg.MinIOBucket
	exists, err := client.BucketExists(context.Background(), bucketName)
	if err != nil {
		return err
	}

	if !exists {
		if err := client.MakeBucket(context.Background(), bucketName, minio.MakeBucketOptions{}); err != nil {
			return err
		}
		log.Printf("MinIO bucket '%s' created", bucketName)
	} else {
		log.Printf("MinIO bucket '%s' already exists", bucketName)
	}

	return nil
}
