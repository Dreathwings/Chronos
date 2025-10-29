# Diagramme du processus de génération

Ce document décrit toutes les étapes qui interviennent lorsqu'une génération automatique est demandée depuis l'interface Chronos. Il couvre les parcours par lot et par cours, la résolution des contraintes avant placement ainsi que les vérifications réalisées après génération.

```mermaid
flowchart TD
    A[Démarrage utilisateur\n(génération ou réévaluation)] --> B{Type d'action}
    B -- "Génération" --> C{Mode}
    C -- "Par lot" --> D[Création d'un job de progression\n`_enqueue_bulk_schedule`]
    C -- "Par cours" --> E[Création d'un job dédié\n`_enqueue_course_schedule`]
    D --> F[Chargement des cours et heures restantes\n`_run_bulk_schedule_job`]
    E --> G[Chargement du cours ciblé\n`_run_course_schedule_job`]
    F --> H{Boucle sur chaque cours}
    G --> I[Initialisation du reporter et de la progression]
    H --> I
    I --> J[Résolution de la fenêtre de planification\n`_resolve_schedule_window`]
    J --> K[Normalisation des semaines autorisées\n+ objectifs hebdomadaires]
    K --> L[Calcul des heures/occurrences requises\n`generate_schedule`]
    L --> M{Type de cours}
    M -- "CM" --> N[Placement CM : recherche de jours communs\n+ relocation intra-semaine]
    M -- "TD/TP" --> O[Placement TD/TP : découpe par sous-groupes\n+ relocation inter-cours autorisée]
    M -- "Autre" --> P[Placement générique par sous-groupes]
    N --> Q{Placement trouvé ?}
    O --> Q
    P --> Q
    Q -- "Oui" --> R[Création de la séance + suivi de progression]
    Q -- "Non" --> S[Collecte des échecs + suggestions\n`ScheduleReporter`]
    R --> T{Cours suivant ?}
    S --> T
    T -- "Oui" --> H
    T -- "Non" --> U[Commit de la session et synthèse\n(journal + flash)]
    B -- "Évaluation" --> V[Analyse de toutes les séances\n`_evaluate_generation_quality`]
    U --> V
    V --> W{Séance conforme ?\n`_validate_session_constraints`}
    W -- "Non" --> X[Ajout d'une anomalie\n(message + classe/enseignant/salle)]
    W -- "Oui" --> Y[Comptage des séances conformes]
    X --> Z[Résultat final\n(messages d'erreur / succès)]
    Y --> Z
```

## Détails des étapes principales

1. **Déclenchement de l'action** – Le formulaire de la page de génération gère les actions de génération, d'évaluation ou de réinitialisation selon la valeur `form`. Les modes par lot et par cours démarrent un thread de fond via `_enqueue_bulk_schedule` ou `_enqueue_course_schedule`. 【F:app/routes.py†L2153-L2247】【F:app/routes.py†L3006-L3149】
2. **Initialisation du travail** – Les jobs récupèrent la progression associée, chargent les cours concernés et initialisent la jauge totale d'heures à produire avant de lancer `generate_schedule`. 【F:app/routes.py†L3040-L3113】
3. **Résolution de la fenêtre** – `generate_schedule` commence par déterminer l'intervalle de planification valide à partir des fenêtres du semestre et des semaines autorisées. 【F:app/scheduler.py†L2522-L2612】
4. **Normalisation des semaines** – Les semaines fournies sont reformatées, filtrées par les périodes de fermeture et converties en objectifs hebdomadaires qui servent de base aux occurrences à placer. 【F:app/scheduler.py†L2613-L2746】
5. **Calcul des besoins** – Après avoir comptabilisé les classes associées et les heures déjà planifiées, la fonction évalue les occurrences restantes et prépare le suivi de progression. 【F:app/scheduler.py†L2747-L2858】
6. **Placement selon le type** – Le bloc CM recherche des journées communes et peut relocaliser des séances existantes ; les blocs TD/TP découpent les sous-groupes et autorisent les relocalisations inter-cours pour récupérer des créneaux ; les autres types utilisent le même mécanisme générique sans relocalisation inter-cours. 【F:app/scheduler.py†L2859-L3099】【F:app/scheduler.py†L3100-L3389】
7. **Gestion des échecs** – En absence de placement possible, les erreurs sont consignées via `ScheduleReporter`, ce qui alimente les messages de synthèse affichés dans l'interface. 【F:app/scheduler.py†L3002-L3040】【F:app/routes.py†L2260-L2335】
8. **Évaluation de conformité** – L'action « Évaluer » parcourt toutes les séances créées et vérifie les contraintes (périodes autorisées, disponibilité enseignants/salles/classes, collisions horaires) via `_validate_session_constraints`. 【F:app/routes.py†L180-L279】【F:app/routes.py†L894-L1182】

Ce diagramme peut servir de référence rapide pour raisonner sur les améliorations futures du moteur de génération ou pour diagnostiquer les points de blocage rencontrés par les utilisateurs.
