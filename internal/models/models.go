package models

import "time"

// RecipeSummary represents the minimal information displayed on the listing pages.
type RecipeSummary struct {
	Slug          string   `json:"slug"`
	Title         string   `json:"title"`
	Tagline       string   `json:"tagline"`
	Image         string   `json:"image"`
	PrepTime      string   `json:"prepTime"`
	Difficulty    string   `json:"difficulty"`
	Cuisine       string   `json:"cuisine"`
	Tags          []string `json:"tags"`
	HfreshURL     string   `json:"hfreshUrl"`
	HelloFreshURL string   `json:"helloFreshUrl"`
}

// Ingredient describes a single ingredient and its quantity.
type Ingredient struct {
	Name     string `json:"name"`
	Quantity string `json:"quantity"`
	Image    string `json:"image"`
}

// Step represents a preparation step.
type Step struct {
	Number      int    `json:"number"`
	Description string `json:"description"`
	Image       string `json:"image"`
}

// RecipeDetail aggregates all data necessary for the recipe page.
type RecipeDetail struct {
	Summary       RecipeSummary `json:"summary"`
	Ingredients   []Ingredient  `json:"ingredients"`
	Steps         []Step        `json:"steps"`
	Tags          []string      `json:"tags"`
	YieldOptions  []int         `json:"yieldOptions"`
	BaseServings  int           `json:"baseServings"`
	LastScrapedAt time.Time     `json:"lastScrapedAt"`
}

// PersistedData stores the scraped catalogue.
type PersistedData struct {
	Recipes     []RecipeSummary `json:"recipes"`
	LastUpdated time.Time       `json:"lastUpdated"`
}
