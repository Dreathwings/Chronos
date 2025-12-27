package storage

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"

	"chronos/internal/models"
)

// Repository keeps scraped recipes and details in memory with optional persistence.
type Repository struct {
	mu      sync.RWMutex
	data    models.PersistedData
	details map[string]models.RecipeDetail
	path    string
}

// NewRepository creates a repository backed by the given JSON file.
func NewRepository(path string) *Repository {
	return &Repository{
		path:    path,
		details: make(map[string]models.RecipeDetail),
	}
}

// Load hydrates the repository from disk if the file exists.
func (r *Repository) Load() error {
	r.mu.Lock()
	defer r.mu.Unlock()

	content, err := os.ReadFile(r.path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}

	var data models.PersistedData
	if err := json.Unmarshal(content, &data); err != nil {
		return err
	}

	r.data = data
	return nil
}

// Save writes the current catalogue to disk.
func (r *Repository) Save() error {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if err := os.MkdirAll(filepath.Dir(r.path), 0o755); err != nil {
		return err
	}

	payload, err := json.MarshalIndent(r.data, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(r.path, payload, 0o644)
}

// ReplaceSummaries overwrites the catalogue with new data.
func (r *Repository) ReplaceSummaries(recipes []models.RecipeSummary, scrapedAt time.Time) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.data = models.PersistedData{
		Recipes:     recipes,
		LastUpdated: scrapedAt,
	}
}

// List returns all recipe summaries.
func (r *Repository) List() []models.RecipeSummary {
	r.mu.RLock()
	defer r.mu.RUnlock()

	out := make([]models.RecipeSummary, len(r.data.Recipes))
	copy(out, r.data.Recipes)
	return out
}

// LastUpdated returns the last scraping time.
func (r *Repository) LastUpdated() time.Time {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.data.LastUpdated
}

// GetSummary retrieves a recipe summary by slug.
func (r *Repository) GetSummary(slug string) (models.RecipeSummary, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, rec := range r.data.Recipes {
		if rec.Slug == slug {
			return rec, true
		}
	}
	return models.RecipeSummary{}, false
}

// StoreDetail caches a recipe detail in memory.
func (r *Repository) StoreDetail(detail models.RecipeDetail) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.details[detail.Summary.Slug] = detail
}

// GetDetail returns a cached detail, if present.
func (r *Repository) GetDetail(slug string) (models.RecipeDetail, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	detail, ok := r.details[slug]
	return detail, ok
}
