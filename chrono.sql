-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Hôte : 127.0.0.1
-- Généré le : lun. 13 oct. 2025 à 03:21
-- Version du serveur : 10.4.32-MariaDB
-- Version de PHP : 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Base de données : `chrono`
--

-- --------------------------------------------------------

--
-- Structure de la table `class_group`
--

CREATE TABLE `class_group` (
  `id` int(11) NOT NULL,
  `name` varchar(150) NOT NULL,
  `size` int(11) NOT NULL,
  `unavailable_dates` text DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `class_group`
--

INSERT INTO `class_group` (`id`, `name`, `size`, `unavailable_dates`, `notes`, `created_at`, `updated_at`) VALUES
(2, 'A1', 24, '', '', '2025-10-12 15:21:37', '2025-10-12 15:21:37'),
(3, 'A2', 20, '', '', '2025-10-12 15:21:43', '2025-10-12 15:21:43'),
(4, 'A3', 20, '', '', '2025-10-12 19:21:56', '2025-10-12 19:21:56'),
(5, 'A4', 20, '', '', '2025-10-12 19:22:00', '2025-10-12 19:22:00');

-- --------------------------------------------------------

--
-- Structure de la table `course`
--

CREATE TABLE `course` (
  `id` int(11) NOT NULL,
  `name` varchar(200) NOT NULL,
  `description` text DEFAULT NULL,
  `session_length_hours` int(11) NOT NULL,
  `sessions_required` int(11) NOT NULL,
  `start_date` date DEFAULT NULL,
  `end_date` date DEFAULT NULL,
  `priority` int(11) NOT NULL,
  `course_type` varchar(3) NOT NULL,
  `requires_computers` tinyint(1) NOT NULL,
  `computers_required` int(11) NOT NULL DEFAULT 0,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ;

--
-- Déchargement des données de la table `course`
--

INSERT INTO `course` (`id`, `name`, `description`, `session_length_hours`, `sessions_required`, `start_date`, `end_date`, `priority`, `course_type`, `requires_computers`, `computers_required`, `created_at`, `updated_at`) VALUES
(1, 'Python Avancé', 'Programmation avancée en Python', 2, 4, '2025-10-11', '2025-11-21', 1, 'TD', 1, 20, '2025-10-11 11:14:23', '2025-10-12 19:48:23');

-- --------------------------------------------------------

--
-- Structure de la table `course_name`
--

CREATE TABLE `course_name` (
  `id` int(11) NOT NULL,
  `name` varchar(120) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `course_name`
--

INSERT INTO `course_name` (`id`, `name`, `created_at`, `updated_at`) VALUES
(1, 'Python Avancé — Groupe A', '2025-10-12 19:45:00', '2025-10-12 19:45:00'),
(2, 'Python Avancé — Groupe B', '2025-10-12 19:45:00', '2025-10-12 19:45:00');

-- --------------------------------------------------------

--
-- Structure de la table `course_class`
--

CREATE TABLE `course_class` (
  `course_id` int(11) NOT NULL,
  `class_group_id` int(11) NOT NULL,
  `group_count` int(11) NOT NULL DEFAULT 1,
  `teacher_a_id` int(11) DEFAULT NULL,
  `teacher_b_id` int(11) DEFAULT NULL,
  `subgroup_a_course_name_id` int(11) DEFAULT NULL,
  `subgroup_b_course_name_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `course_class`
--

INSERT INTO `course_class` (`course_id`, `class_group_id`, `group_count`, `teacher_a_id`, `teacher_b_id`, `subgroup_a_course_name_id`, `subgroup_b_course_name_id`) VALUES
(1, 3, 2, 3, 3, 1, 2),
(1, 5, 1, 1, NULL, NULL, NULL);

-- --------------------------------------------------------

--
-- Structure de la table `course_equipment`
--

CREATE TABLE `course_equipment` (
  `course_id` int(11) NOT NULL,
  `equipment_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `course_equipment`
--

INSERT INTO `course_equipment` (`course_id`, `equipment_id`) VALUES
(1, 1);

-- --------------------------------------------------------

--
-- Structure de la table `course_software`
--

CREATE TABLE `course_software` (
  `course_id` int(11) NOT NULL,
  `software_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `course_software`
--

INSERT INTO `course_software` (`course_id`, `software_id`) VALUES
(1, 1);

-- --------------------------------------------------------

--
-- Structure de la table `course_teacher`
--

CREATE TABLE `course_teacher` (
  `course_id` int(11) NOT NULL,
  `teacher_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `course_teacher`
--

INSERT INTO `course_teacher` (`course_id`, `teacher_id`) VALUES
(1, 1),
(1, 2);

-- --------------------------------------------------------

--
-- Structure de la table `course_schedule_log`
--

CREATE TABLE `course_schedule_log` (
  `id` int(11) NOT NULL,
  `course_id` int(11) NOT NULL,
  `status` varchar(20) NOT NULL DEFAULT 'success',
  `summary` text DEFAULT NULL,
  `messages` text NOT NULL,
  `window_start` date DEFAULT NULL,
  `window_end` date DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `course_schedule_log`
--

-- --------------------------------------------------------

--
-- Structure de la table `closing_period`
--

CREATE TABLE `closing_period` (
  `id` int(11) NOT NULL,
  `start_date` date NOT NULL,
  `end_date` date NOT NULL,
  `label` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `closing_period`
--

-- --------------------------------------------------------

--
-- Structure de la table `equipment`
--

CREATE TABLE `equipment` (
  `id` int(11) NOT NULL,
  `name` varchar(120) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `equipment`
--

INSERT INTO `equipment` (`id`, `name`) VALUES
(1, 'Vidéo-projecteur');

-- --------------------------------------------------------

--
-- Structure de la table `room`
--

CREATE TABLE `room` (
  `id` int(11) NOT NULL,
  `name` varchar(120) NOT NULL,
  `capacity` int(11) NOT NULL,
  `computers` int(11) NOT NULL,
  `notes` text DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `room`
--

INSERT INTO `room` (`id`, `name`, `capacity`, `computers`, `notes`, `created_at`, `updated_at`) VALUES
(3, '101.b (Festo)', 20, 0, '', '2025-10-12 16:21:41', '2025-10-12 16:21:41'),
(4, '101.a (Robotique)', 20, 0, '', '2025-10-12 16:23:19', '2025-10-12 16:23:19'),
(6, '101.c (Automatisme)', 20, 0, '', '2025-10-12 16:23:46', '2025-10-12 16:23:46'),
(7, '102', 20, 0, '', '2025-10-12 16:23:50', '2025-10-12 16:23:50'),
(8, '103 (C&C)', 20, 0, '', '2025-10-12 16:23:56', '2025-10-12 16:23:56'),
(9, '104', 20, 0, '', '2025-10-12 16:24:00', '2025-10-12 16:24:00'),
(10, '105 (C&C)', 20, 0, '', '2025-10-12 16:24:04', '2025-10-12 16:24:04'),
(11, '106', 20, 0, '', '2025-10-12 16:24:11', '2025-10-12 16:24:11'),
(12, '108-110 (Automatisme)', 20, 0, '', '2025-10-12 16:24:18', '2025-10-12 16:24:18'),
(13, '112', 20, 0, '', '2025-10-12 16:24:23', '2025-10-12 16:24:23'),
(14, '114', 20, 0, '', '2025-10-12 16:24:26', '2025-10-12 16:24:26'),
(15, '037 (TPOL2 La PLAGE)', 24, 24, '', '2025-10-12 16:24:53', '2025-10-12 19:49:34'),
(16, '033 (Automatique)', 20, 0, '', '2025-10-12 16:24:58', '2025-10-12 16:24:58'),
(17, '032 (Energie 2A)', 20, 0, '', '2025-10-12 16:25:02', '2025-10-12 16:25:02'),
(18, '031 (Energie 1A)', 20, 0, '', '2025-10-12 16:25:07', '2025-10-12 16:25:07'),
(19, '030 (Réseau)', 24, 24, '', '2025-10-12 16:25:11', '2025-10-12 19:48:58'),
(20, '029 (Hab. Elec.)', 20, 0, '', '2025-10-12 16:25:15', '2025-10-12 16:25:15'),
(21, '028.b (MEEDD)', 20, 0, '', '2025-10-12 16:25:19', '2025-10-12 16:25:19'),
(22, '028.a (Energie 2A)', 20, 0, '', '2025-10-12 16:25:23', '2025-10-12 16:25:23'),
(23, '027 (SAE 2A)', 20, 0, '', '2025-10-12 16:25:28', '2025-10-12 16:25:28'),
(24, '026 (SAE 1A)', 20, 0, '', '2025-10-12 16:25:33', '2025-10-12 16:25:33'),
(25, '025 (TP ELN 1A)', 20, 0, '', '2025-10-12 16:25:36', '2025-10-12 16:25:36'),
(26, '024 (TP II 1A)', 20, 0, '', '2025-10-12 16:25:40', '2025-10-12 16:25:40'),
(27, '023 (TP II 2A)', 20, 0, '', '2025-10-12 16:25:44', '2025-10-12 16:25:44'),
(28, '021 (TPOL1)', 20, 0, '', '2025-10-12 16:25:47', '2025-10-12 16:25:47'),
(29, '020 (CAfIEM)', 20, 0, '', '2025-10-12 16:25:51', '2025-10-12 16:25:51'),
(30, '019 (TP ELN 2A)', 20, 0, '', '2025-10-12 16:25:55', '2025-10-12 16:25:55'),
(31, '016 (LSI)', 20, 0, '', '2025-10-12 16:26:00', '2025-10-12 16:26:00'),
(32, '012 (Anglais)', 20, 0, '', '2025-10-12 16:26:04', '2025-10-12 16:26:04'),
(33, '011 (Anglais)', 20, 0, '', '2025-10-12 16:26:07', '2025-10-12 16:26:07');

-- --------------------------------------------------------

--
-- Structure de la table `room_equipment`
--

CREATE TABLE `room_equipment` (
  `room_id` int(11) NOT NULL,
  `equipment_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `room_equipment`
--

INSERT INTO `room_equipment` (`room_id`, `equipment_id`) VALUES
(15, 1),
(19, 1);

-- --------------------------------------------------------

--
-- Structure de la table `room_software`
--

CREATE TABLE `room_software` (
  `room_id` int(11) NOT NULL,
  `software_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `room_software`
--

INSERT INTO `room_software` (`room_id`, `software_id`) VALUES
(15, 1),
(19, 1);

-- --------------------------------------------------------

--
-- Structure de la table `session`
--

CREATE TABLE `session` (
  `id` int(11) NOT NULL,
  `course_id` int(11) NOT NULL,
  `teacher_id` int(11) NOT NULL,
  `room_id` int(11) NOT NULL,
  `start_time` datetime NOT NULL,
  `end_time` datetime NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `class_group_id` int(11) NOT NULL,
  `subgroup_label` varchar(1) DEFAULT NULL
) ;

--
-- Déchargement des données de la table `session`
--

INSERT INTO `session` (`id`, `course_id`, `teacher_id`, `room_id`, `start_time`, `end_time`, `created_at`, `updated_at`, `class_group_id`, `subgroup_label`) VALUES
(123, 1, 1, 15, '2025-10-16 08:00:00', '2025-10-16 10:00:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 3, NULL),
(124, 1, 2, 15, '2025-10-28 15:45:00', '2025-10-28 17:45:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 3, NULL),
(125, 1, 1, 15, '2025-11-06 15:45:00', '2025-11-06 17:45:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 3, NULL),
(126, 1, 2, 15, '2025-11-18 15:45:00', '2025-11-18 17:45:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 3, NULL),
(127, 1, 1, 15, '2025-10-16 15:45:00', '2025-10-16 17:45:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 5, NULL),
(128, 1, 1, 15, '2025-10-28 10:15:00', '2025-10-28 12:15:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 5, NULL),
(129, 1, 2, 19, '2025-11-06 15:45:00', '2025-11-06 17:45:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 5, NULL),
(130, 1, 1, 15, '2025-11-18 10:15:00', '2025-11-18 12:15:00', '2025-10-13 01:18:12', '2025-10-13 01:18:12', 5, NULL);

-- --------------------------------------------------------

--
-- Structure de la table `session_attendance`
--

CREATE TABLE `session_attendance` (
  `session_id` int(11) NOT NULL,
  `class_group_id` int(11) NOT NULL,
  PRIMARY KEY (`session_id`, `class_group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `session_attendance`
--

INSERT INTO `session_attendance` (`session_id`, `class_group_id`) VALUES
(123, 3),
(124, 3),
(125, 3),
(126, 3),
(127, 5),
(128, 5),
(129, 5),
(130, 5);

-- --------------------------------------------------------

--
-- Structure de la table `software`
--

CREATE TABLE `software` (
  `id` int(11) NOT NULL,
  `name` varchar(120) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `software`
--

INSERT INTO `software` (`id`, `name`) VALUES
(1, 'VS Code');

-- --------------------------------------------------------

--
-- Structure de la table `teacher`
--

CREATE TABLE `teacher` (
  `id` int(11) NOT NULL,
  `name` varchar(120) NOT NULL,
  `email` varchar(255) DEFAULT NULL,
  `phone` varchar(50) DEFAULT NULL,
  `available_from` time NOT NULL,
  `available_until` time NOT NULL,
  `unavailable_dates` text DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `teacher`
--

INSERT INTO `teacher` (`id`, `name`, `email`, `phone`, `available_from`, `available_until`, `unavailable_dates`, `notes`, `created_at`, `updated_at`) VALUES
(1, 'Alice Martin', 'zdzd@dzdzd.dzdz', 'Nonez', '08:00:00', '18:00:00',  '[{\"start\": \"2025-10-13\", \"end\": \"2025-10-13\"}, {\"start\": \"2025-10-20\", \"end\": \"2025-10-21\"}]', 'None', '2025-10-11 11:14:23', '2025-10-12 13:35:01'),
(2, 'Loic Theolier', 'aasa@efz.ca', '', '00:00:00', '00:00:00', NULL, '', '2025-10-12 22:01:43', '2025-10-12 22:01:43'),
(3, 'Simon Hemour', 'qzdq@qzd.dqzd', '', '00:00:00', '00:00:00', NULL, '', '2025-10-12 22:02:04', '2025-10-12 22:02:04');

-- --------------------------------------------------------

--
-- Structure de la table `teacher_availability`
--

CREATE TABLE `teacher_availability` (
  `id` int(11) NOT NULL,
  `teacher_id` int(11) NOT NULL,
  `weekday` int(11) NOT NULL,
  `start_time` time NOT NULL,
  `end_time` time NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL
) ;

--
-- Déchargement des données de la table `teacher_availability`
--

INSERT INTO `teacher_availability` (`id`, `teacher_id`, `weekday`, `start_time`, `end_time`, `created_at`, `updated_at`) VALUES
(32, 1, 0, '10:15:00', '12:15:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(33, 1, 0, '13:30:00', '15:30:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(34, 1, 1, '10:15:00', '12:15:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(35, 1, 1, '13:30:00', '15:30:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(36, 1, 2, '08:00:00', '10:00:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(37, 1, 2, '10:15:00', '12:15:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(38, 1, 3, '08:00:00', '10:00:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(39, 1, 3, '10:15:00', '12:15:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(40, 1, 3, '13:30:00', '15:30:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(41, 1, 3, '15:45:00', '17:45:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(42, 1, 4, '08:00:00', '10:00:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(43, 1, 4, '10:15:00', '12:15:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(44, 1, 4, '13:30:00', '15:30:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(45, 1, 4, '15:45:00', '17:45:00', '2025-10-11 20:21:11', '2025-10-11 20:21:11'),
(46, 3, 0, '08:00:00', '10:00:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(47, 3, 0, '10:15:00', '12:15:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(48, 3, 0, '13:30:00', '15:30:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(49, 3, 0, '15:45:00', '17:45:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(50, 3, 1, '13:30:00', '15:30:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(51, 3, 1, '15:45:00', '17:45:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(52, 3, 2, '08:00:00', '10:00:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(53, 3, 2, '10:15:00', '12:15:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(54, 3, 2, '13:30:00', '15:30:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(55, 3, 2, '15:45:00', '17:45:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(56, 3, 3, '08:00:00', '10:00:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(57, 3, 3, '10:15:00', '12:15:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(58, 3, 3, '13:30:00', '15:30:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(59, 3, 3, '15:45:00', '17:45:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(60, 3, 4, '13:30:00', '15:30:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(61, 3, 4, '15:45:00', '17:45:00', '2025-10-12 22:02:43', '2025-10-12 22:02:43'),
(62, 2, 0, '10:15:00', '12:15:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(63, 2, 0, '13:30:00', '15:30:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(64, 2, 0, '15:45:00', '17:45:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(65, 2, 1, '10:15:00', '12:15:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(66, 2, 1, '13:30:00', '15:30:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(67, 2, 1, '15:45:00', '17:45:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(68, 2, 2, '10:15:00', '12:15:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(69, 2, 2, '13:30:00', '15:30:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(70, 2, 2, '15:45:00', '17:45:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(71, 2, 3, '10:15:00', '12:15:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(72, 2, 3, '13:30:00', '15:30:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(73, 2, 3, '15:45:00', '17:45:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(74, 2, 4, '10:15:00', '12:15:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(75, 2, 4, '13:30:00', '15:30:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14'),
(76, 2, 4, '15:45:00', '17:45:00', '2025-10-12 22:03:14', '2025-10-12 22:03:14');

--
-- Index pour les tables déchargées
--

--
-- Index pour la table `class_group`
--
ALTER TABLE `class_group`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `name` (`name`);

--
-- Index pour la table `course`
--
ALTER TABLE `course`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `name` (`name`);

--
-- Index pour la table `course_class`
--
ALTER TABLE `course_class`
  ADD PRIMARY KEY (`course_id`,`class_group_id`),
  ADD KEY `class_group_id` (`class_group_id`);

--
-- Index pour la table `course_equipment`
--
ALTER TABLE `course_equipment`
  ADD PRIMARY KEY (`course_id`,`equipment_id`),
  ADD KEY `equipment_id` (`equipment_id`);

--
-- Index pour la table `course_software`
--
ALTER TABLE `course_software`
  ADD PRIMARY KEY (`course_id`,`software_id`),
  ADD KEY `software_id` (`software_id`);

--
-- Index pour la table `course_teacher`
--
ALTER TABLE `course_teacher`
  ADD PRIMARY KEY (`course_id`,`teacher_id`),
  ADD KEY `teacher_id` (`teacher_id`);

--
-- Index pour la table `course_schedule_log`
--
ALTER TABLE `course_schedule_log`
  ADD PRIMARY KEY (`id`),
  ADD KEY `course_schedule_log_course_id_idx` (`course_id`),
  ADD KEY `course_schedule_log_created_idx` (`created_at`);

--
-- Index pour la table `closing_period`
--
ALTER TABLE `closing_period`
  ADD PRIMARY KEY (`id`),
  ADD KEY `closing_period_start_idx` (`start_date`),
  ADD KEY `closing_period_end_idx` (`end_date`);

--
-- Index pour la table `equipment`
--
ALTER TABLE `equipment`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `name` (`name`);

--
-- Index pour la table `room`
--
ALTER TABLE `room`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `name` (`name`);

--
-- Index pour la table `room_equipment`
--
ALTER TABLE `room_equipment`
  ADD PRIMARY KEY (`room_id`,`equipment_id`),
  ADD KEY `equipment_id` (`equipment_id`);

--
-- Index pour la table `room_software`
--
ALTER TABLE `room_software`
  ADD PRIMARY KEY (`room_id`,`software_id`),
  ADD KEY `software_id` (`software_id`);

--
-- Index pour la table `session`
--
ALTER TABLE `session`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uq_room_start_time` (`room_id`,`start_time`),
  ADD KEY `course_id` (`course_id`),
  ADD KEY `teacher_id` (`teacher_id`),
  ADD KEY `session_class_group_fk` (`class_group_id`);

--
-- Index pour la table `software`
--
ALTER TABLE `software`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `name` (`name`);

--
-- Index pour la table `teacher`
--
ALTER TABLE `teacher`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `name` (`name`);

--
-- Index pour la table `teacher_availability`
--
ALTER TABLE `teacher_availability`
  ADD PRIMARY KEY (`id`),
  ADD KEY `teacher_id` (`teacher_id`);

--
-- AUTO_INCREMENT pour les tables déchargées
--

--
-- AUTO_INCREMENT pour la table `class_group`
--
ALTER TABLE `class_group`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;

--
-- AUTO_INCREMENT pour la table `course`
--
ALTER TABLE `course`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT pour la table `course_schedule_log`
--
ALTER TABLE `course_schedule_log`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT pour la table `closing_period`
--
ALTER TABLE `closing_period`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT pour la table `equipment`
--
ALTER TABLE `equipment`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT pour la table `room`
--
ALTER TABLE `room`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=34;

--
-- AUTO_INCREMENT pour la table `session`
--
ALTER TABLE `session`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT pour la table `software`
--
ALTER TABLE `software`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT pour la table `teacher`
--
ALTER TABLE `teacher`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT pour la table `teacher_availability`
--
ALTER TABLE `teacher_availability`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- Contraintes pour les tables déchargées
--

--
-- Contraintes pour la table `course_class`
--
ALTER TABLE `course_class`
  ADD CONSTRAINT `course_class_ibfk_1` FOREIGN KEY (`course_id`) REFERENCES `course` (`id`),
  ADD CONSTRAINT `course_class_ibfk_2` FOREIGN KEY (`class_group_id`) REFERENCES `class_group` (`id`);

--
-- Contraintes pour la table `course_equipment`
--
ALTER TABLE `course_equipment`
  ADD CONSTRAINT `course_equipment_ibfk_1` FOREIGN KEY (`course_id`) REFERENCES `course` (`id`),
  ADD CONSTRAINT `course_equipment_ibfk_2` FOREIGN KEY (`equipment_id`) REFERENCES `equipment` (`id`);

--
-- Contraintes pour la table `course_software`
--
ALTER TABLE `course_software`
  ADD CONSTRAINT `course_software_ibfk_1` FOREIGN KEY (`course_id`) REFERENCES `course` (`id`),
  ADD CONSTRAINT `course_software_ibfk_2` FOREIGN KEY (`software_id`) REFERENCES `software` (`id`);

--
-- Contraintes pour la table `course_teacher`
--
ALTER TABLE `course_teacher`
  ADD CONSTRAINT `course_teacher_ibfk_1` FOREIGN KEY (`course_id`) REFERENCES `course` (`id`),
  ADD CONSTRAINT `course_teacher_ibfk_2` FOREIGN KEY (`teacher_id`) REFERENCES `teacher` (`id`);

--
-- Contraintes pour la table `course_schedule_log`
--
ALTER TABLE `course_schedule_log`
  ADD CONSTRAINT `course_schedule_log_course_fk` FOREIGN KEY (`course_id`) REFERENCES `course` (`id`);

--
-- Contraintes pour la table `room_equipment`
--
ALTER TABLE `room_equipment`
  ADD CONSTRAINT `room_equipment_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `room` (`id`),
  ADD CONSTRAINT `room_equipment_ibfk_2` FOREIGN KEY (`equipment_id`) REFERENCES `equipment` (`id`);

--
-- Contraintes pour la table `room_software`
--
ALTER TABLE `room_software`
  ADD CONSTRAINT `room_software_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `room` (`id`),
  ADD CONSTRAINT `room_software_ibfk_2` FOREIGN KEY (`software_id`) REFERENCES `software` (`id`);

--
-- Contraintes pour la table `session`
--
ALTER TABLE `session`
  ADD CONSTRAINT `session_class_group_fk` FOREIGN KEY (`class_group_id`) REFERENCES `class_group` (`id`),
  ADD CONSTRAINT `session_ibfk_1` FOREIGN KEY (`course_id`) REFERENCES `course` (`id`),
  ADD CONSTRAINT `session_ibfk_2` FOREIGN KEY (`teacher_id`) REFERENCES `teacher` (`id`),
  ADD CONSTRAINT `session_ibfk_3` FOREIGN KEY (`room_id`) REFERENCES `room` (`id`);

--
-- Contraintes pour la table `teacher_availability`
--
ALTER TABLE `teacher_availability`
  ADD CONSTRAINT `teacher_availability_ibfk_1` FOREIGN KEY (`teacher_id`) REFERENCES `teacher` (`id`);
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
