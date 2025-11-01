# Étapes de la génération des emplois du temps

1. **Constitution des semaines cibles**  
   La fenêtre de planification du cours est normalisée (dates du semestre, filtre éventuel sur les semaines autorisées, suppression des périodes de fermeture) afin d'obtenir une liste ordonnée de semaines actives et des jours travaillés (lundi → vendredi).

2. **Construction des demandes de séances**
   Pour chaque cours, on calcule les heures restantes à planifier par type de séance (CM, SAE/EVAL, TD, TP). Les classes et sous-groupes concernés alimentent une file d'attente de « demandes de séances » à traiter. Les quotas hebdomadaires saisis via les champs `allowed-week-sessions-AAAA-MM-JJ` sont interprétés comme un nombre maximal de séances à positionner sur la semaine correspondante.

3. **Itération semaine par semaine**  
   On parcourt les semaines disponibles dans l'ordre chronologique. À chaque semaine, les demandes restantes sont triées selon la priorité CM → SAE → EVAL → TD → TP.

4. **Placement de chaque demande**  
   Pour une demande donnée, on recherche un créneau valide : vérification de l'indisponibilité des classes et des enseignants, respect de la chronologie CM → TD → TP, vérification des salles (capacité, matériel/PC). On privilégie les sessions d'1 h immédiatement adjacentes à une séance existante.

5. **Suivi des ressources et de la progression**
   À chaque placement réussi on met à jour les compteurs de progression, l'état d'allocation des enseignants et les statistiques journalières. Les quotas hebdomadaires sont décrémentés au fil des placements, et un tableau de suivi s'affiche dans la fenêtre de progression pour indiquer, semaine par semaine, les séances planifiées, en attente ou reportées. Les séances non planifiées sont reportées sur la semaine suivante.

6. **Contrôles de cohérence**  
   Après chaque semaine, des avertissements sont émis lorsque des séances d'1 h ne sont pas consécutives ou lorsque la planification ne respecte pas l'ordre CM → TD → TP → Éval. En fin de parcours, un résumé global est enregistré (succès ou échec partiel).

7. **Gestion des échecs**  
   Si certaines demandes ne peuvent être satisfaites, elles sont listées dans le rapport final pour guider les actions correctives (élargir les disponibilités, ajouter des salles, etc.).
