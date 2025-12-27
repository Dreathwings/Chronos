package main

import (
	"log"
	"net/http"
	"os"
	"strconv"

	"chronos/internal/server"
	"chronos/internal/storage"
)

func main() {
	baseURL := getenv("HFRESH_SOURCE", "https://hfresh.info")
	port := getenv("PORT", "3044")
	maxPages := getenvInt("SCRAPER_MAX_PAGES", 25)

	repo := storage.NewRepository("data/recipes.json")
	if err := repo.Load(); err != nil {
		log.Fatalf("impossible de charger les données : %v", err)
	}

	srv, err := server.New(baseURL, repo, maxPages)
	if err != nil {
		log.Fatalf("serveur indisponible : %v", err)
	}

	log.Printf("Serveur disponible sur :%s (source %s)", port, baseURL)
	if err := http.ListenAndServe(":"+port, srv.Router()); err != nil {
		log.Fatalf("erreur serveur : %v", err)
	}
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func getenvInt(key string, fallback int) int {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.Atoi(value); err == nil {
			return parsed
		}
	}
	return fallback
}
