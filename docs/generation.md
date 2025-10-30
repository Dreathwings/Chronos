# Système de génération des emplois du temps

Ce document résume les étapes suivies par le nouveau moteur de planification automatique.

## 1. Préparation des demandes de séances
- Chaque cours est analysé pour déterminer le nombre de séances restantes à programmer.
- Les séances sont transformées en *demandes* (`SessionRequest`) en appliquant les règles de volume par type :
  - **CM** : une seule séance regroupant toutes les classes rattachées au cours.
  - **SAE** : une séance par classe avec deux enseignants attendus.
  - **TD / EVAL** : une séance par classe avec un enseignant.
  - **TP** : une séance par demi-groupe lorsque la classe est scindée.
- Chaque demande mémorise les enseignants préférés associés au cours ou au lien classe ↔ cours.

## 2. Découpage hebdomadaire et détection des indisponibilités
- La fenêtre de planification est bornée par le semestre et les éventuelles semaines autorisées.
- Pour chaque semaine comprise dans cette fenêtre, on contrôle les périodes de fermeture globales (`ClosingPeriod`) et les indisponibilités déclarées par les enseignants ou les classes.
- Les semaines autorisées fournissent un quota hebdomadaire ; les séances excédentaires sont reportées sur la semaine suivante.

## 3. Recherche des créneaux compatibles
- Pour chaque demande de séance, les jours ouvrés de la semaine sont parcourus, en respectant les plages horaires de travail (`WORKING_WINDOWS`).
- Les classes concernées doivent être disponibles sur le créneau pressenti.
- Le moteur cherche à réutiliser le même enseignant d'une séance à l'autre ; à défaut il examine les enseignants préférés, ceux du cours puis le reste du corps enseignant.
- Une salle est sélectionnée si elle respecte la capacité, le nombre de postes informatiques et les équipements requis.
- Tous les créneaux compatibles sont enregistrés dans la demande afin de conserver les alternatives.

## 4. Placement ou repositionnement
- Si un créneau valide est trouvé, la séance est créée et liée à la classe, à l'enseignant retenu et à la salle.
- Si aucun créneau n'est disponible sur la semaine, la demande est conservée pour la semaine suivante.
- Les diagnostics collectent les raisons (classe, enseignant, salle) ayant empêché la planification pour faciliter les ajustements.

## 5. Report et clôture
- À la fin de chaque semaine, les demandes non planifiées sont ajoutées en fin de file pour la semaine suivante.
- Lorsque toutes les semaines ont été explorées, les demandes restantes déclenchent un message d'erreur résumant les séances impossibles à placer.
- Le suivi de progression (`ScheduleProgress`) est mis à jour à chaque séance créée et clôturé à la fin du processus.
