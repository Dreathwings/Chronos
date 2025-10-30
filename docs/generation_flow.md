# Diagramme du nouveau processus de génération

Ce document illustre la nouvelle orchestration de la génération automatique. Elle conserve le suivi de progression existant tout en introduisant un moteur hebdomadaire qui trie les séances par type, vérifie les indisponibilités, sélectionne les enseignants et tente les placements avec relocalisation ciblée avant de reporter les restes sur la semaine suivante.

```mermaid
flowchart TD
    A[Démarrage utilisateur\n(génération ou réévaluation)] --> B{Type d'action}
    B -- "Génération" --> C[Initialisation du suivi de progression\n`ScheduleProgressTracker`]
    C --> D[Planificateur hebdomadaire\n`WeeklyGenerationPlanner.run`]
    D --> E[Collecte des semaines et fenêtres\nautorisées]
    E --> F[Pour chaque semaine : filtrage des jours\nde fermeture et d'indisponibilité globale]
    F --> G[Tri des cours actifs et des séances\npar type (CM → SAE → Eval → TD → TP)]
    G --> H[Pour chaque séance :<br/>• attribution d'un enseignant prioritaire<br/>• construction de l'EDT croisé classe/enseignant<br/>• recherche de créneaux compatibles]
    H --> I{Créneau trouvé ?}
    I -- "Oui" --> J[Création des séances<br/>+ réservation des salles et ressources<br/>+ mise à jour de la progression]
    I -- "Non" --> K[Recherche de relocalisations<br/>(TD/TP seulement) pour libérer un créneau]
    K --> L{Relocalisation possible ?}
    L -- "Oui" --> J
    L -- "Non" --> M[Reporter la séance en fin de<br/>file de la semaine suivante]
    J --> N{Fin des séances de la semaine ?}
    M --> N
    N -- "Non" --> G
    N -- "Oui" --> O[Passage à la semaine suivante]
    O --> P{Cours restants ?}
    P -- "Oui" --> E
    P -- "Non" --> Q[Clôture de la génération]
    B -- "Évaluation" --> R[Analyse des séances générées\n`_evaluate_generation_quality`]
    Q --> R
    R --> S{Séance conforme ?\n`_validate_session_constraints`}
    S -- "Non" --> T[Signalement des anomalies\n(classe/enseignant/salle)]
    S -- "Oui" --> U[Comptage des séances conformes]
    T --> V[Résultat final]
    U --> V
```

## Détails des étapes principales

1. **Initialisation et suivi** – L'interface déclenche un travail de fond qui réinitialise la jauge globale et crée une tranche de progression pour chaque couple cours/semaine traité par `WeeklyGenerationPlanner`. 【F:app/routes.py†L3040-L3149】【F:app/generation.py†L66-L123】
2. **Préparation hebdomadaire** – Le planificateur agrège toutes les semaines autorisées par cours, élimine celles fermées par un `ClosingPeriod` et ne conserve que les jours ouvrés exploitables. 【F:app/generation.py†L33-L87】
3. **Ordonnancement des séances** – Pour chaque semaine, seuls les cours encore actifs sont retenus puis triés suivant l'ordre de priorité `CM`, `SAE`, `Eval`, `TD`, `TP`. Le nombre d'occurrences à produire est borné par l'objectif hebdomadaire du cours. 【F:app/generation.py†L14-L21】【F:app/generation.py†L89-L124】
4. **Sélection des enseignants et créneaux** – Lors du placement d'une séance, `generate_schedule` recherche d'abord la continuité pédagogique en privilégiant l'enseignant déjà assigné puis reconstruit l'emploi du temps croisé classe/enseignant pour trouver des créneaux qui respectent capacités, besoins matériels et disponibilité des ressources. 【F:app/scheduler.py†L2747-L2986】【F:app/scheduler.py†L2987-L3175】
5. **Relocalisation ciblée** – Si aucun créneau n'est disponible, le planificateur déclenche la logique de relocalisation spécifique aux TD/TP pour déplacer une autre séance de la semaine et libérer l'espace nécessaire avant de réessayer. 【F:app/scheduler.py†L3176-L3389】
6. **Report sur la semaine suivante** – Les séances qui n'ont pas pu être placées sont automatiquement ajoutées à la fin de la file de la semaine suivante ; si aucune fenêtre restante n'est compatible, un message d'erreur est renvoyé à l'utilisateur en fin de traitement. 【F:app/generation.py†L125-L159】
7. **Évaluation de conformité** – L'action « Évaluer » reste disponible à la fin de la génération ; elle vérifie chaque séance à l'aide de `_validate_session_constraints` pour détecter les conflits de ressources ou de calendrier. 【F:app/routes.py†L180-L279】【F:app/routes.py†L2153-L2247】

Ce schéma sert de référence pour comprendre le comportement du nouveau moteur de génération, diagnostiquer les blocages éventuels et planifier les futures améliorations.
