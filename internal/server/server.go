package server

import (
	"context"
	"embed"
	"fmt"
	"html/template"
	"io/fs"
	"log"
	"math"
	"net/http"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"chronos/internal/models"
	"chronos/internal/scraper"
	"chronos/internal/storage"
)

//go:embed web/templates/*.gohtml web/static/*
var webFS embed.FS

type Server struct {
	BaseURL       string
	MaxPages      int
	Repo          *storage.Repository
	templates     *template.Template
	staticHandler http.Handler
	shopping      *shoppingStore
}

type shoppingStore struct {
	mu    sync.RWMutex
	lists map[string]*ShoppingList
}

type ShoppingList struct {
	Entries []ShoppingEntry
}

type ShoppingEntry struct {
	RecipeSlug string
	Servings   int
}

// New constructs a Server configured against the given scraper baseURL.
func New(baseURL string, repo *storage.Repository, maxPages int) (*Server, error) {
	funcs := template.FuncMap{
		"contains": strings.Contains,
		"hasTag": func(tags []string, value string) bool {
			for _, t := range tags {
				if strings.EqualFold(t, value) {
					return true
				}
			}
			return false
		},
		"join": strings.Join,
		"isZeroTime": func(t time.Time) bool {
			return t.IsZero()
		},
	}

	tmpl, err := template.New("root").Funcs(funcs).ParseFS(webFS, "web/templates/*.gohtml")
	if err != nil {
		return nil, err
	}

	static, err := fsSub("web/static")
	if err != nil {
		return nil, err
	}

	return &Server{
		BaseURL:       baseURL,
		MaxPages:      maxPages,
		Repo:          repo,
		templates:     tmpl,
		staticHandler: http.FileServer(http.FS(static)),
		shopping: &shoppingStore{
			lists: map[string]*ShoppingList{},
		},
	}, nil
}

// Router returns the configured HTTP handler.
func (s *Server) Router() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleHome)
	mux.HandleFunc("/menus", s.handleMenu)
	mux.HandleFunc("/menus/", s.handleMenu)
	mux.HandleFunc("/recipes/", s.handleRecipeDetail)
	mux.HandleFunc("/refresh", s.handleRefresh)
	mux.HandleFunc("/shopping-list", s.handleShoppingList)
	mux.HandleFunc("/shopping-list/add", s.handleAddToShoppingList)
	mux.HandleFunc("/shopping-list/remove", s.handleRemoveFromShoppingList)
	mux.Handle("/static/", http.StripPrefix("/static/", s.staticHandler))
	return loggingMiddleware(mux)
}

// handleHome renders the full catalogue with filters.
func (s *Server) handleHome(w http.ResponseWriter, r *http.Request) {
	if err := s.ensureCatalogue(r.Context()); err != nil {
		http.Error(w, fmt.Sprintf("scraping failed: %v", err), http.StatusInternalServerError)
		return
	}

	query := r.URL.Query()
	recipes := s.Repo.List()
	recipes = filterRecipes(recipes, query)
	slices.SortFunc(recipes, func(a, b models.RecipeSummary) int {
		return strings.Compare(strings.ToLower(a.Title), strings.ToLower(b.Title))
	})

	data := map[string]any{
		"Recipes":      recipes,
		"Filters":      buildFilters(query),
		"Available":    buildFilterOptions(s.Repo.List()),
		"LastUpdated":  s.Repo.LastUpdated(),
		"PageTitle":    "Recettes",
		"ShoppingPath": "/shopping-list",
	}
	s.render(w, "home", data)
}

func (s *Server) handleMenu(w http.ResponseWriter, r *http.Request) {
	week := strings.TrimPrefix(r.URL.Path, "/menus/")

	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()

	recipes, title, err := scraper.ScrapeMenu(ctx, s.BaseURL, week)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	filtered := filterRecipes(recipes, r.URL.Query())
	data := map[string]any{
		"Recipes":      filtered,
		"PageTitle":    title,
		"Filters":      buildFilters(r.URL.Query()),
		"Available":    buildFilterOptions(recipes),
		"LastUpdated":  time.Now(),
		"ShoppingPath": "/shopping-list",
	}
	s.render(w, "home", data)
}

func (s *Server) handleRecipeDetail(w http.ResponseWriter, r *http.Request) {
	slug := strings.TrimPrefix(r.URL.Path, "/recipes/")
	if slug == "" {
		http.NotFound(w, r)
		return
	}

	detail, err := s.ensureDetail(r.Context(), slug)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	data := map[string]any{
		"Recipe":       detail,
		"PageTitle":    detail.Summary.Title,
		"ShoppingPath": "/shopping-list",
	}
	s.render(w, "detail", data)
}

func (s *Server) handleRefresh(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST seulement", http.StatusMethodNotAllowed)
		return
	}

	maxPages := s.MaxPages
	if requested := r.URL.Query().Get("pages"); requested != "" {
		if requested == "all" {
			maxPages = 0
		} else if n, err := strconv.Atoi(requested); err == nil {
			maxPages = n
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
	defer cancel()

	recipes, err := scraper.ScrapeSummaries(ctx, s.BaseURL, maxPages)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	s.Repo.ReplaceSummaries(recipes, time.Now())
	if err := s.Repo.Save(); err != nil {
		http.Error(w, fmt.Sprintf("Impossible d'enregistrer: %v", err), http.StatusInternalServerError)
		return
	}

	http.Redirect(w, r, "/", http.StatusSeeOther)
}

func (s *Server) handleShoppingList(w http.ResponseWriter, r *http.Request) {
	listID, list := s.ensureList(r, w)
	recipes := s.Repo.List()
	recipeLookup := make(map[string]models.RecipeSummary, len(recipes))
	for _, rec := range recipes {
		recipeLookup[rec.Slug] = rec
	}

	ingredientSummary, entries := s.aggregateIngredients(r.Context(), list)
	data := map[string]any{
		"PageTitle":          "Liste de courses",
		"ListID":             listID,
		"Entries":            entries,
		"Ingredients":        ingredientSummary,
		"Recipes":            recipeLookup,
		"ShoppingPath":       "/shopping-list",
		"LastUpdated":        s.Repo.LastUpdated(),
		"AvailableSummaries": s.Repo.List(),
	}

	s.render(w, "shopping", data)
}

func (s *Server) handleAddToShoppingList(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Méthode non autorisée", http.StatusMethodNotAllowed)
		return
	}

	if err := r.ParseForm(); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	slug := r.FormValue("slug")
	servings, _ := strconv.Atoi(r.FormValue("servings"))
	if servings <= 0 {
		servings = 2
	}

	if slug == "" {
		http.Redirect(w, r, "/shopping-list", http.StatusSeeOther)
		return
	}

	// ensure we can load the recipe before adding to the basket
	if _, err := s.ensureDetail(r.Context(), slug); err != nil {
		http.Error(w, fmt.Sprintf("Impossible d'ajouter la recette : %v", err), http.StatusBadGateway)
		return
	}

	_, list := s.ensureList(r, w)
	list.Entries = append(list.Entries, ShoppingEntry{RecipeSlug: slug, Servings: servings})
	http.Redirect(w, r, "/shopping-list", http.StatusSeeOther)
}

func (s *Server) handleRemoveFromShoppingList(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Méthode non autorisée", http.StatusMethodNotAllowed)
		return
	}

	if err := r.ParseForm(); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	index, err := strconv.Atoi(r.FormValue("index"))
	if err != nil {
		http.Redirect(w, r, "/shopping-list", http.StatusSeeOther)
		return
	}

	_, list := s.ensureList(r, w)
	if index >= 0 && index < len(list.Entries) {
		list.Entries = append(list.Entries[:index], list.Entries[index+1:]...)
	}
	http.Redirect(w, r, "/shopping-list", http.StatusSeeOther)
}

func (s *Server) ensureCatalogue(ctx context.Context) error {
	if len(s.Repo.List()) > 0 {
		return nil
	}

	recipes, err := scraper.ScrapeSummaries(ctx, s.BaseURL, s.MaxPages)
	if err != nil {
		return err
	}
	s.Repo.ReplaceSummaries(recipes, time.Now())
	return s.Repo.Save()
}

func (s *Server) ensureDetail(ctx context.Context, slug string) (models.RecipeDetail, error) {
	if detail, ok := s.Repo.GetDetail(slug); ok {
		return detail, nil
	}

	detail, err := scraper.ScrapeDetail(ctx, s.BaseURL, slug)
	if err != nil {
		return models.RecipeDetail{}, err
	}

	s.Repo.StoreDetail(detail)
	return detail, nil
}

func (s *Server) ensureList(r *http.Request, w http.ResponseWriter) (string, *ShoppingList) {
	cookie, _ := r.Cookie("chronos_list")
	var listID string
	if cookie != nil {
		listID = cookie.Value
	}

	if listID == "" {
		listID = uuid.NewString()
		http.SetCookie(w, &http.Cookie{
			Name:    "chronos_list",
			Value:   listID,
			Expires: time.Now().Add(30 * 24 * time.Hour),
			Path:    "/",
		})
	}

	s.shopping.mu.Lock()
	defer s.shopping.mu.Unlock()

	list, ok := s.shopping.lists[listID]
	if !ok {
		list = &ShoppingList{}
		s.shopping.lists[listID] = list
	}
	return listID, list
}

type aggregatedIngredient struct {
	Name       string
	Quantity   string
	Recipes    []string
	Unit       string
	parsed     bool
	numericQty float64
}

func (s *Server) aggregateIngredients(ctx context.Context, list *ShoppingList) ([]aggregatedIngredient, []ShoppingEntry) {
	aggregate := map[string]*aggregatedIngredient{}

	for _, entry := range list.Entries {
		detail, err := s.ensureDetail(ctx, entry.RecipeSlug)
		if err != nil {
			log.Printf("unable to hydrate %s: %v", entry.RecipeSlug, err)
			continue
		}

		factor := float64(entry.Servings) / float64(max(1, detail.BaseServings))
		for _, ing := range detail.Ingredients {
			key := ing.Name
			acc, ok := aggregate[key]
			if !ok {
				acc = &aggregatedIngredient{Name: ing.Name, Recipes: []string{}}
				aggregate[key] = acc
			}

			acc.Recipes = append(acc.Recipes, fmt.Sprintf("%s (%d pers.)", detail.Summary.Title, entry.Servings))
			if qty, unit, ok := parseQuantity(ing.Quantity); ok {
				acc.parsed = true
				acc.Unit = unit
				acc.numericQty += qty * factor
			} else if acc.Quantity == "" {
				acc.Quantity = ing.Quantity
			}
		}
	}

	out := make([]aggregatedIngredient, 0, len(aggregate))
	for _, acc := range aggregate {
		if acc.parsed {
			value := acc.numericQty
			acc.Quantity = formatAmount(value)
			if acc.Unit != "" {
				acc.Quantity += " " + acc.Unit
			}
		}
		out = append(out, *acc)
	}

	slices.SortFunc(out, func(a, b aggregatedIngredient) int {
		return strings.Compare(strings.ToLower(a.Name), strings.ToLower(b.Name))
	})
	return out, list.Entries
}

func parseQuantity(q string) (float64, string, bool) {
	q = strings.TrimSpace(q)
	if q == "" {
		return 0, "", false
	}

	fractions := map[string]float64{
		"¼": 0.25,
		"½": 0.5,
		"¾": 0.75,
	}

	parts := strings.Fields(q)
	if len(parts) == 0 {
		return 0, "", false
	}

	rawNumber := parts[0]
	var number float64

	if v, ok := fractions[rawNumber]; ok {
		number = v
	} else if strings.Contains(rawNumber, "/") {
		split := strings.Split(rawNumber, "/")
		if len(split) == 2 {
			num, _ := strconv.ParseFloat(split[0], 64)
			den, _ := strconv.ParseFloat(split[1], 64)
			if num > 0 && den > 0 {
				number = num / den
			}
		}
	} else {
		value := strings.ReplaceAll(rawNumber, ",", ".")
		val, err := strconv.ParseFloat(value, 64)
		if err != nil {
			return 0, "", false
		}
		number = val
	}

	if number == 0 {
		return 0, "", false
	}

	unit := strings.TrimSpace(strings.TrimPrefix(q, parts[0]))
	return number, unit, true
}

func formatAmount(value float64) string {
	rounded := math.Round(value*100) / 100
	if math.Abs(rounded-math.Round(rounded)) < 0.001 {
		return fmt.Sprintf("%.0f", rounded)
	}
	return fmt.Sprintf("%.2f", rounded)
}

func buildFilters(values url.Values) map[string]any {
	return map[string]any{
		"Query":      values.Get("q"),
		"Difficulty": values.Get("difficulty"),
		"Tags":       values["tag"],
		"Cuisine":    values.Get("cuisine"),
	}
}

func buildFilterOptions(recipes []models.RecipeSummary) map[string][]string {
	tagSet := map[string]struct{}{}
	difficultySet := map[string]struct{}{}
	cuisineSet := map[string]struct{}{}

	for _, r := range recipes {
		if r.Difficulty != "" {
			difficultySet[r.Difficulty] = struct{}{}
		}
		if r.Cuisine != "" {
			cuisineSet[r.Cuisine] = struct{}{}
		}
		for _, t := range r.Tags {
			tagSet[t] = struct{}{}
		}
	}

	return map[string][]string{
		"Tags":       keys(tagSet),
		"Difficulty": keys(difficultySet),
		"Cuisine":    keys(cuisineSet),
	}
}

func keys(set map[string]struct{}) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	slices.Sort(out)
	return out
}

func filterRecipes(recipes []models.RecipeSummary, values url.Values) []models.RecipeSummary {
	query := strings.ToLower(values.Get("q"))
	difficulty := strings.TrimSpace(values.Get("difficulty"))
	cuisine := strings.TrimSpace(values.Get("cuisine"))
	tags := values["tag"]

	var filtered []models.RecipeSummary
	for _, r := range recipes {
		if query != "" && !strings.Contains(strings.ToLower(r.Title+" "+r.Tagline), query) {
			continue
		}
		if difficulty != "" && !strings.EqualFold(r.Difficulty, difficulty) {
			continue
		}
		if cuisine != "" && !strings.EqualFold(r.Cuisine, cuisine) {
			continue
		}
		if len(tags) > 0 && !containsAllTags(r.Tags, tags) {
			continue
		}
		filtered = append(filtered, r)
	}
	return filtered
}

func containsAllTags(have, expected []string) bool {
	for _, tag := range expected {
		found := false
		for _, h := range have {
			if strings.EqualFold(h, tag) {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

func (s *Server) render(w http.ResponseWriter, content string, data map[string]any) {
	if data == nil {
		data = map[string]any{}
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	if err := s.templates.ExecuteTemplate(w, content, data); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		log.Printf("%s %s in %s", r.Method, r.URL.Path, time.Since(start))
	})
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// fsSub returns a filesystem sub-directory from the embedded assets.
func fsSub(dir string) (fs.FS, error) {
	return fs.Sub(webFS, dir)
}
