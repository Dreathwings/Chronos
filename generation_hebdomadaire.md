# Processus de génération hebdomadaire

Cette note décrit les principales étapes désormais suivies par la génération automatique afin de planifier les séances semaine par semaine.

## 1. Sélection des cours par semaine
* Pour chaque cours, on construit une liste de semaines autorisées via `build_weekly_targets`.
* Les semaines sont ensuite fusionnées pour établir une chronologie globale.
* À l'ouverture d'une semaine, on ne retient que les cours ayant encore des heures à placer et autorisés sur la période considérée.
* Les cours actifs sont triés par type selon l'ordre métier **CM → SAE → TD → TP → EVAL**, puis par nom, afin de respecter la priorité demandée pour chaque semaine.

## 2. Prise en compte des indisponibilités
* Avant toute tentative de placement, l'algorithme conserve les validations existantes (indisponibilités générales et individuelles).
* Les contraintes globales (périodes de fermeture) et celles des enseignants sont vérifiées par `generate_schedule` qui reste responsable des contrôles fins.

## 3. Affectation des enseignants et recherche de créneaux
* Pour chaque cours actif, on fixe un objectif de **séances** pour la semaine (cible + report des séances non planifiées précédemment).
* `generate_schedule` est invoqué avec une fenêtre d'une semaine, conserve le suivi de progression existant **et plafonne la création de séances à l'objectif fixé pour la semaine**.
* L'algorithme essaie de conserver l'enseignant utilisé sur les séances précédentes tout en respectant les besoins en capacité, matériel et postes informatiques.

## 4. Gestion des reports
* Après chaque tentative, on mesure le nombre réel de séances planifiées.
* Toute séance non planifiée est reportée sur la semaine suivante afin de conserver le suivi exact des occurrences (y compris pour les sous-groupes hétérogènes).
* En cas d'échec complet, l'erreur est mémorisée pour diagnostic tout en laissant les séances en attente.

## 5. Replanification globale si nécessaire
* Lorsqu'aucun créneau n'est trouvé, le moteur tente désormais de déplacer automatiquement les séances d'autres cours en conflit sur la même semaine (pour les mêmes classes).
* Les cours déplacés conservent un reliquat de séances afin d'être replanifiés lors des semaines suivantes.

## 6. Passage à la semaine suivante
* Lorsque tous les cours ont été traités pour la semaine courante, on passe à la semaine suivante.
* Les cours qui conservent un reliquat restent éligibles et bénéficient d'un objectif augmenté la semaine suivante.
* À l'issue des semaines disponibles, les cours encore incomplets sont signalés dans le rapport final.
