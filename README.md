# Chronos — Planificateur d'emplois du temps

Application Flask permettant de gérer enseignants, salles, cours et ressources pour construire un emploi du temps optimisé. Chaque section dispose d'une interface web dédiée avec calendrier FullCalendar pour visualiser les séances programmées.

## Fonctionnalités

- Tableau de bord avec calendrier global et formulaire de planification rapide.
- Gestion des enseignants (créneaux de disponibilité hebdomadaires, jours d'indisponibilité, charge hebdomadaire maximale) et assignation aux cours.
- Gestion des classes (effectifs, indisponibilités ponctuelles) avec association aux cours et calendrier dédié.
- Gestion des salles avec capacités, postes informatiques, matériels et logiciels disponibles.
- Gestion des cours avec contraintes (nombre de séances, durée, période de planification, priorité, équipements et logiciels requis, besoin en ordinateurs) et assignation multi-enseignants.
- Référentiels centralisés pour les matériels et logiciels utilisés lors de la planification.
- Génération automatique de séances respectant les contraintes (créneaux 8h-18h avec pauses définies, disponibilités enseignants et classes, capacités des salles, matériel/logiciel requis).
- Affichage des calendriers individuels (enseignant, classe, salle, cours) via FullCalendar avec grisage automatique des pauses et plages hors planning.
- Édition directe des séances dans les calendriers (glisser-déposer pour déplacer, clic pour supprimer) avec validation serveur des contraintes.

## Prérequis

- Python 3.11+
- MariaDB 10.6+ (optionnel si vous utilisez SQLite pour des tests locaux)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Créez un fichier `.env` (optionnel) pour définir la clé secrète et les informations de connexion à la base de données :

```env
SECRET_KEY=change-me
DATABASE_USER=root
DATABASE_PASSWORD=chronos
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATABASE_NAME=chronos
FLASK_URL_PREFIX=
```

Avec ces variables, l'application utilisera par défaut la base MySQL `chronos` exposée sur le port `3306` avec l'utilisateur `root` et le mot de passe `chronos`. Vous pouvez également fournir directement `DATABASE_URL`; dans ce cas, il prendra le pas sur les variables ci-dessus.

`FLASK_URL_PREFIX` permet de servir l'application derrière un proxy en la plaçant sous un sous-chemin (par exemple `/chronos`). Laissez la valeur vide pour conserver les routes à la racine.
## Lancement

```bash
flask --app app run --debug
```

À la première exécution l'application crée les tables automatiquement. Vous pouvez injecter des données de démonstration :

```bash
flask --app app seed
```

Les principales pages sont accessibles via :

- `/` : tableau de bord et calendrier global
- `/enseignant` : liste des enseignants
- `/enseignant/<id>` : fiche enseignant + calendrier personnel
- `/classe` : liste des classes
- `/classe/<id>` : fiche classe + calendrier dédié
- `/salle` : liste des salles
- `/salle/<id>` : fiche salle + calendrier des réservations
- `/matiere` : liste des cours
- `/matiere/<id>` : fiche cours, contraintes et génération automatique
- `/equipement` : gestion des matériels
- `/logiciel` : gestion des logiciels

## Tests rapides

Pour vérifier que les dépendances Python sont installées correctement :

```bash
python -m compileall app
```

## Notes techniques

- L'algorithme de génération automatique divise la plage de dates disponible par le nombre de séances à produire pour chaque classe, calcule un jour « ancre » pour chaque séance puis explore les journées les plus proches de cette ancre tant qu'une ressource valide n'a pas été trouvée. Les heures de début sont pivotées en fonction du rang de la séance afin d'explorer l'ensemble des créneaux horaires disponibles et de mieux répartir les cours sur la plage possible, tout en respectant les contraintes (professeur disponible, salle adéquate, ressources requises et charge hebdomadaire maximale).
- Les pauses sont prises en compte avec les créneaux suivants : 08h-09h, 09h-10h, 10h15-11h15, 11h15-12h15, 13h30-14h30, 14h30-15h30, 15h45-16h45, 16h45-17h45.
- Les calendriers sont générés côté client avec FullCalendar (CDN), affichent les journées de 07h à 19h et grisent automatiquement les pauses ainsi que les plages indisponibles (enseignants et classes).

## Paramétrer l'auto-placement des cours

Pour utiliser la génération automatique depuis la fiche d'un cours (`/matiere/<id>`), assurez-vous que :

1. **Le cours est correctement paramétré** :
   - Renseignez les dates de début et de fin, le nombre de séances requises et la durée d'une séance dans le formulaire « Contraintes du cours ».
   - Associez au moins une classe au cours, ainsi que les enseignants susceptibles d'intervenir, les équipements/logiciels requis et le besoin éventuel en ordinateurs.
2. **Les ressources sont prêtes** :
   - Pour chaque enseignant sélectionné, configurez ses disponibilités hebdomadaires et sa charge maximale dans l'onglet enseignant afin que l'algorithme puisse vérifier la disponibilité et le volume horaire.
   - Vérifiez que les salles disposent de capacités, d'ordinateurs, de matériels et de logiciels conformes aux contraintes du cours.
   - Saisissez les indisponibilités ponctuelles des classes si nécessaire afin d'éviter des conflits.
3. **Lancez la génération** :
   - Depuis la fiche du cours, cliquez sur **« Générer automatiquement »**. L'application créera autant de séances que nécessaire en respectant les fenêtres horaires de travail (08h-18h avec pauses définies) et en cherchant un créneau compatible pour la classe, un enseignant disponible et une salle adaptée.

En cas d'échec (séances restantes), un avertissement est consigné dans les logs et vous pouvez compléter la planification manuellement à l'aide du formulaire « Ajouter une séance manuelle ».

## Modifier le comportement de l'algorithme

L'algorithme de génération automatique est centralisé dans [`app/scheduler.py`](app/scheduler.py). Les principales zones à ajuster sont :

- **Plages de travail et créneaux testés** : les constantes `WORKING_WINDOWS`, `SCHEDULE_SLOTS` et `START_TIMES` définissent respectivement les amplitudes journalières autorisées, les découpages d'une heure utilisés pour tester un placement, ainsi que la liste des heures de début. Modifiez-les pour élargir ou restreindre les journées travaillées, ou pour tester des durées différentes (par exemple des créneaux de 90 minutes).
- **Heuristiques de priorisation** : les fonctions `find_available_teacher` et `find_available_room` appliquent les critères de tri (capacité croissante pour les salles, charge hebdomadaire maximale pour les enseignants). Vous pouvez y modifier l'ordre de tri ou ajouter d'autres critères (distance entre salles, préférences d'affectation…) avant le filtre sur les conflits. Dans `generate_schedule`, `_spread_sequence` est utilisé pour permuter les heures de début tandis qu'une recherche autour d'un jour « ancre » (déterminé par la répartition homogène des séances) explore les journées voisines ; adaptez ces mécanismes si vous souhaitez d'autres stratégies de répartition.
- **Gestion des contraintes supplémentaires** : ajoutez vos propres validations dans `generate_schedule` (ex. interdire deux séances consécutives pour une même classe) en insérant des `continue` lorsque les nouvelles règles ne sont pas respectées.
- **Journalisation et retours utilisateur** : personnalisez les messages envoyés dans les logs via `current_app.logger` pour faciliter le diagnostic, ou complétez la réponse HTTP renvoyée dans `app/routes.py` lorsque `generate_schedule` échoue.

Après toute modification, relancez la commande `flask --app app run --debug` afin de recharger le serveur, puis effectuez une génération automatique sur un cours test pour valider le nouveau comportement.

## Licence

MIT
