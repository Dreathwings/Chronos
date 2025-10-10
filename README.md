# Planificateur d’emplois du temps — Flask + MariaDB

Gestion et optimisation automatisée d’emplois du temps selon:
- disponibilités enseignants  
- capacités et équipements des salles  
- besoins des cours (durée, fenêtres de dates, logiciels, PC)

## Architecture cible
- **API**: Flask + Flask-RESTX (Swagger)
- **ORM**: SQLAlchemy + Alembic
- **DB**: MariaDB 10.6+
- **Optimisation**: OR-Tools (CP-SAT)
- **Config**: `.env`
- **Conteneurs**: Docker + docker-compose
- **Tests**: pytest

## Démarrage rapide (en local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Adapter DATABASE_URL si besoin (voir section XAMPP ci-dessous)
flask --app app db upgrade
python seed.py
flask --app app run --debug --port 8000
```

L'API est disponible sous `http://localhost:8000/api` et la documentation Swagger sur `http://localhost:8000/api/docs`.

## Variables d’environnement (`.env.example`)
```
FLASK_ENV=development
SECRET_KEY=change_me
DATABASE_URL=mysql+pymysql://root:@127.0.0.1:3306/chronos
DB_ECHO=false
API_TITLE=Chronos API
API_VERSION=0.1.0
ORIGIN=http://localhost:8000
```

## Connexion à MariaDB via XAMPP

1. Lancez le panneau de contrôle XAMPP et démarrez les services **Apache** et **MySQL**.
2. Ouvrez [http://localhost/phpmyadmin](http://localhost/phpmyadmin) puis créez une base `chronos` (utf8mb4 recommandé).
3. (Optionnel mais conseillé) Créez un utilisateur dédié `chronos` avec un mot de passe et tous les privilèges sur la base.
4. Ajustez `DATABASE_URL` dans `.env` selon vos identifiants. Exemples :
   - `mysql+pymysql://root:@127.0.0.1:3306/chronos`
   - `mysql+pymysql://chronos:motdepasse@127.0.0.1:3306/chronos`
5. Depuis votre terminal, appliquez le schéma avec `flask --app app db upgrade`.
6. Exécutez `python seed.py` pour charger des données de démonstration (enseignants, salles, classes, créneaux horaires, etc.).

> 💡 Le connecteur Python utilisé par défaut est `PyMySQL` (pur Python, compatible MariaDB/MySQL). Aucun composant natif n'est requis. Vous pouvez néanmoins utiliser un autre driver SQLAlchemy (`mariadb+mariadbconnector`, `mysql+mysqlclient`, etc.) en adaptant `DATABASE_URL` et les dépendances si besoin.

## Schéma de données (résumé)

- **teachers**: id, name, max_weekly_load_hrs  
- **teacher_availabilities**: id, teacher_id, weekday, start_time, end_time  
- **teacher_unavailabilities**: id, teacher_id, date, start_time, end_time  
- **class_groups**: id, code, name, size, notes
- **rooms**: id, name, capacity, building
- **room_equipment**: id, room_id, key, value  
- **courses**: id, name, group_id, size, teacher_id, sessions_count, session_minutes, window_start, window_end  
- **course_requirements**: id, course_id, key, value  
- **timeslots**: id, date, start_time, end_time, minutes  
- **assignments**: id, course_id, session_index, timeslot_id, room_id, teacher_id, status

## Endpoints principaux

- `POST /api/teachers` CRUD enseignants  
- `POST /api/rooms` CRUD salles  
- `POST /api/courses` CRUD cours  
- `POST /api/timeslots/generate` génère les créneaux potentiels  
- `POST /api/solve` lance l’optimiseur  
- `GET /api/timetable?scope=teacher|group|room&id=...` vue filtrée
- `PATCH /api/assignments/{id}` ajustement manuel
- `GET /api/health` statut

## Interface Web d'administration

En complément de l'API, Chronos fournit une interface HTML responsive accessible sur `http://localhost:8000/`. Elle permet de :

- Visualiser un tableau de bord (effectifs, dernières créations).
- Gérer les **salles** (création, suppression, équipements sous forme `clé=valeur`).
- Gérer les **enseignants** (création, suppression, charge hebdomadaire maximale).
- Définir les disponibilités hebdomadaires grâce au calendrier dédié et enregistrer des périodes d'indisponibilité ponctuelle.
- Gérer les **classes** (code, intitulé, effectif, notes). La suppression est bloquée si des cours sont associés.
- Gérer les **cours** (sélection d'une classe et d'un enseignant, fenêtres de dates, exigences `clé=valeur`).

Les formulaires intègrent des validations basiques et des messages de confirmation/erreur. Les actions reposent sur la même base de données que l'API, ce qui permet d'enchaîner gestion manuelle et appels programmatiques sans désynchronisation.

## Règles horaires et génération des créneaux

Les créneaux proposés par Chronos durent 60 minutes et respectent la journée standard de 08h00 à 18h00 avec les pauses imposées :

- 08h00 – 09h00
- 09h00 – 10h00
- 10h15 – 11h15 (pause de 10h00 à 10h15)
- 11h15 – 12h15
- 13h30 – 14h30 (pause déjeuner de 12h15 à 13h30, soit 1h15 entre 12h et 14h)
- 14h30 – 15h30
- 15h45 – 16h45 (pause de 15h30 à 15h45)
- 16h45 – 17h45

L'endpoint `POST /api/timeslots/generate` valide désormais que la durée demandée reste à 60 minutes et que la plage journalière couvre au moins 08:00 à 17:45. Le calendrier web reprend exactement ces créneaux : il suffit de cocher les heures souhaitées pour un enseignant, puis d'ajouter au besoin des indisponibilités ponctuelles pour bloquer des journées spécifiques.

## Génération du code avec Codex
(voir le README complet fourni précédemment)

## Licence
MIT.
