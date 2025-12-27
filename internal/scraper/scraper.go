package scraper

import (
	"context"
	"fmt"
	"html"
	"net/http"
	"net/url"
	"path"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"

	"chronos/internal/models"
)

var httpClient = &http.Client{Timeout: 20 * time.Second}

// ScrapeSummaries returns recipe cards from the paginated listing.
// maxPages <= 0 scrapes until no more pages are found.
func ScrapeSummaries(ctx context.Context, baseURL string, maxPages int) ([]models.RecipeSummary, error) {
	var results []models.RecipeSummary
	seen := make(map[string]struct{})
	page := 1

	for {
		if maxPages > 0 && page > maxPages {
			break
		}

		listURL := fmt.Sprintf("%s/fr-FR?page=%d", strings.TrimSuffix(baseURL, "/"), page)
		doc, err := fetchDocument(ctx, listURL)
		if err != nil {
			return nil, fmt.Errorf("fetch page %d: %w", page, err)
		}

		pageCards := parseRecipeCards(doc, baseURL)
		if len(pageCards) == 0 {
			break
		}

		for _, card := range pageCards {
			if _, ok := seen[card.Slug]; ok {
				continue
			}
			seen[card.Slug] = struct{}{}
			results = append(results, card)
		}

		page++
	}

	return results, nil
}

// ScrapeMenu scrapes the weekly menu; weekSlug can be empty to pick the current week.
func ScrapeMenu(ctx context.Context, baseURL, weekSlug string) ([]models.RecipeSummary, string, error) {
	target := fmt.Sprintf("%s/fr-FR/menus", strings.TrimSuffix(baseURL, "/"))
	if weekSlug != "" {
		target = fmt.Sprintf("%s/%s", target, weekSlug)
	}

	doc, err := fetchDocument(ctx, target)
	if err != nil {
		return nil, "", err
	}

	title := strings.TrimSpace(doc.Find("meta[property='og:title']").AttrOr("content", "Menu de la semaine"))
	cards := parseRecipeCards(doc, baseURL)
	return cards, title, nil
}

// ScrapeDetail fetches the detail page for a recipe slug.
func ScrapeDetail(ctx context.Context, baseURL, slug string) (models.RecipeDetail, error) {
	target := fmt.Sprintf("%s/fr-FR/recipes/%s", strings.TrimSuffix(baseURL, "/"), slug)
	doc, err := fetchDocument(ctx, target)
	if err != nil {
		return models.RecipeDetail{}, err
	}

	metaTitle := doc.Find("meta[property='og:title']").AttrOr("content", "")
	if metaTitle == "" {
		metaTitle = doc.Find("title").First().Text()
	}
	title := strings.TrimSpace(strings.TrimSuffix(metaTitle, "· Base de données HelloFresh"))

	description := doc.Find("meta[name='description']").AttrOr("content", "")
	image := doc.Find("meta[property='og:image']").AttrOr("content", "")
	helloFreshURL := doc.Find("a[href^=\"https://www.hellofresh.\"]").First().AttrOr("href", "")

	prepTime, difficulty, cuisine := extractMetaChips(doc)
	tags := extractBadgesNearHeading(doc, "Tags")
	ingredients, baseServings, yields := extractIngredients(doc)
	steps := extractSteps(doc)

	summary := models.RecipeSummary{
		Slug:          slug,
		Title:         html.UnescapeString(title),
		Tagline:       strings.TrimSpace(description),
		Image:         image,
		PrepTime:      prepTime,
		Difficulty:    difficulty,
		Cuisine:       cuisine,
		Tags:          tags,
		HfreshURL:     target,
		HelloFreshURL: helloFreshURL,
	}

	return models.RecipeDetail{
		Summary:       summary,
		Ingredients:   ingredients,
		Steps:         steps,
		Tags:          tags,
		YieldOptions:  yields,
		BaseServings:  baseServings,
		LastScrapedAt: time.Now(),
	}, nil
}

func fetchDocument(ctx context.Context, target string) (*goquery.Document, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "ChronosScraper/1.0 (+https://hfresh.info)")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("unexpected status %s", resp.Status)
	}

	return goquery.NewDocumentFromReader(resp.Body)
}

func parseRecipeCards(doc *goquery.Document, baseURL string) []models.RecipeSummary {
	var cards []models.RecipeSummary

	doc.Find("div[data-flux-card]").Each(func(_ int, card *goquery.Selection) {
		link := card.Find("a[href*='/recipes/']").First()
		href, exists := link.Attr("href")
		if !exists {
			return
		}

		u, err := url.Parse(href)
		if err != nil {
			return
		}
		_, slug := path.Split(strings.TrimSuffix(u.Path, "/"))
		if slug == "" {
			return
		}

		title := strings.TrimSpace(link.Text())
		if title == "" {
			title = strings.TrimSpace(card.Find("[data-flux-heading]").First().Text())
		}

		image := card.Find("img").First().AttrOr("src", "")
		tagline := strings.TrimSpace(card.Find("p[data-flux-text]").First().Text())

		var prepTime, difficulty string
		metaSpans := card.Find("div.mt-3 span")
		if metaSpans.Length() > 0 {
			prepTime = strings.TrimSpace(metaSpans.First().Text())
			if metaSpans.Length() > 1 {
				difficulty = strings.TrimSpace(metaSpans.Eq(1).Text())
			}
		}

		var tags []string
		card.Find("div[data-flux-badge]").Each(func(_ int, tag *goquery.Selection) {
			label := cleanText(tag.Text())
			if label != "" && !slices.Contains(tags, label) {
				tags = append(tags, label)
			}
		})

		helloURL := card.Find("a[href^='https://www.hellofresh.']").First().AttrOr("href", "")
		cards = append(cards, models.RecipeSummary{
			Slug:          slug,
			Title:         html.UnescapeString(title),
			Tagline:       html.UnescapeString(tagline),
			Image:         image,
			PrepTime:      prepTime,
			Difficulty:    difficulty,
			Tags:          tags,
			HfreshURL:     fmt.Sprintf("%s/fr-FR/recipes/%s", strings.TrimSuffix(baseURL, "/"), slug),
			HelloFreshURL: helloURL,
		})
	})

	return cards
}

func cleanText(value string) string {
	value = html.UnescapeString(value)
	return strings.Join(strings.Fields(value), " ")
}

func extractMetaChips(doc *goquery.Document) (prepTime, difficulty, cuisine string) {
	doc.Find("div.flex.flex-wrap span").Each(func(_ int, span *goquery.Selection) {
		text := cleanText(span.Text())
		switch {
		case prepTime == "" && strings.Contains(text, "min"):
			prepTime = text
		case difficulty == "" && strings.Contains(strings.ToLower(text), "difficult"):
			difficulty = strings.TrimPrefix(text, "Difficulté:")
			difficulty = strings.TrimSpace(difficulty)
		case cuisine == "":
			cuisine = text
		}
	})
	return
}

func extractBadgesNearHeading(doc *goquery.Document, heading string) []string {
	var tags []string
	doc.Find("[data-flux-heading]").Each(func(_ int, h *goquery.Selection) {
		if strings.EqualFold(strings.TrimSpace(h.Text()), heading) {
			container := h.Parent()
			container.Find("div[data-flux-badge]").Each(func(_ int, badge *goquery.Selection) {
				label := cleanText(badge.Text())
				if label != "" && !slices.Contains(tags, label) {
					tags = append(tags, label)
				}
			})
		}
	})
	return tags
}

func extractIngredients(doc *goquery.Document) ([]models.Ingredient, int, []int) {
	var ingredients []models.Ingredient
	var yields []int

	doc.Find("[data-flux-heading]").Each(func(_ int, h *goquery.Selection) {
		if strings.TrimSpace(h.Text()) != "Ingrédients" {
			return
		}

		card := h.ParentsFiltered("[data-flux-card]").First()
		if card.Length() == 0 {
			card = h.Parent()
		}

		card.Find("[data-flux-button-group] button span").Each(func(_ int, s *goquery.Selection) {
			val := strings.TrimSpace(s.Text())
			if num, err := parseInt(val); err == nil && !slices.Contains(yields, num) {
				yields = append(yields, num)
			}
		})

		card.Find("div.flex.items-center.gap-3").Each(func(_ int, row *goquery.Selection) {
			name := cleanText(row.Find("p[data-flux-text]").First().Text())
			quantity := cleanText(row.Find("p[data-flux-text]").Last().Text())
			image := row.Find("img").First().AttrOr("src", "")

			if name != "" {
				ingredients = append(ingredients, models.Ingredient{
					Name:     name,
					Quantity: quantity,
					Image:    image,
				})
			}
		})
	})

	baseServings := 2
	for _, y := range yields {
		if y == 2 {
			baseServings = 2
			break
		}
	}
	if len(yields) > 0 && baseServings == 2 && !slices.Contains(yields, 2) {
		baseServings = yields[0]
	}

	return ingredients, baseServings, yields
}

var stepNumberRegexp = regexp.MustCompile(`^\d+`)

func extractSteps(doc *goquery.Document) []models.Step {
	var steps []models.Step

	doc.Find("[data-flux-heading]").Each(func(_ int, h *goquery.Selection) {
		if strings.TrimSpace(strings.ToLower(h.Text())) != "preparation" {
			return
		}

		container := h.Parent()
		container.Find("div.flex.gap-4").Each(func(_ int, block *goquery.Selection) {
			numberText := cleanText(block.Find("div.shrink-0").First().Text())
			number, _ := parseInt(numberText)
			desc := cleanText(block.Find("p[data-flux-text]").First().Text())
			image := block.Find("img").First().AttrOr("src", "")

			if number == 0 && len(steps) > 0 {
				number = steps[len(steps)-1].Number + 1
			}

			if desc != "" {
				steps = append(steps, models.Step{
					Number:      number,
					Description: desc,
					Image:       image,
				})
			}
		})
	})

	return steps
}

func parseInt(value string) (int, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0, fmt.Errorf("empty")
	}

	digits := stepNumberRegexp.FindString(value)
	if digits == "" {
		return 0, fmt.Errorf("no digits in %q", value)
	}

	var number int
	_, err := fmt.Sscan(digits, &number)
	return number, err
}
