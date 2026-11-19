import unittest
from unittest.mock import patch

from navigation import (
    angular_difference, finish_move, forward_route, make_route, new_navigation,
    select_direction, start_move, update_navigation,
)


class RouteSelectionTests(unittest.TestCase):
    def test_angular_difference_wraps_and_is_symmetric(self):
        for first, second, expected in [(0, 0, 0), (359, 1, 2), (540, 0, 180), (-20, 20, 40)]:
            with self.subTest(first=first, second=second):
                self.assertEqual(angular_difference(first, second), expected)
                self.assertEqual(angular_difference(second, first), expected)

    def test_straight_road(self):
        ahead, back = make_route("ahead", 90), make_route("back", 270)
        self.assertEqual(forward_route(95, [back, ahead]), ahead)

    def test_intersection_prefers_the_closest_heading(self):
        routes = [make_route("left", 330), make_route("right", 40), make_route("back", 190)]
        self.assertEqual(forward_route(10, routes)["pano"], "right")
        self.assertEqual(forward_route(350, routes)["pano"], "left")

    def test_empty_or_misaligned_routes(self):
        self.assertIsNone(forward_route(0, []))
        self.assertIsNone(forward_route(0, [make_route("right", 61), make_route("back", 180)]))
        self.assertEqual(forward_route(0, [make_route("right", 60)])["pano"], "right")


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.nav = new_navigation()
        update_navigation(self.nav, "start", 90, [
            make_route("west", 270), make_route("east", 90), make_route("north", 0),
        ])

    @patch("navigation.monotonic")
    def test_history_is_committed_after_success_and_popped_on_back(self, clock):
        clock.return_value = 1
        movement, _ = start_move(self.nav, "forward")
        self.assertEqual(movement["target"], "east")
        self.assertEqual(self.nav["history"], [])
        self.assertIsNone(start_move(self.nav, "back")[0])
        update_navigation(self.nav, "east", 92, [])
        self.assertEqual(self.nav["pano"], "start")
        self.assertTrue(finish_move(self.nav, "east"))
        self.assertEqual(self.nav["history"], ["start"])
        self.assertIsNone(start_move(self.nav, "back")[0])  # Cooldown.

        clock.return_value = 2
        self.assertEqual(start_move(self.nav, "back")[0]["target"], "start")
        self.assertEqual(self.nav["history"], ["start"])
        self.assertTrue(finish_move(self.nav, "start"))
        self.assertEqual(self.nav["history"], [])
        self.assertEqual(self.nav["pano"], "start")

    @patch("navigation.monotonic", return_value=1)
    def test_failed_move_keeps_history_and_current_panorama(self, clock):
        start_move(self.nav, "forward")
        self.assertFalse(finish_move(self.nav, "unexpected"))
        self.assertEqual(self.nav["pano"], "start")
        self.assertEqual(self.nav["history"], [])
        self.assertIsNone(self.nav["pending"])

        clock.return_value = 2
        start_move(self.nav, "forward")
        finish_move(self.nav, "east")
        clock.return_value = 3
        start_move(self.nav, "back")
        self.assertFalse(finish_move(self.nav, ""))
        self.assertEqual(self.nav["pano"], "east")
        self.assertEqual(self.nav["history"], ["start"])

    def test_cycle_wraps_and_confirm_uses_highlighted_route(self):
        self.assertEqual(select_direction(self.nav, 1)["pano"], "east")
        self.assertEqual(select_direction(self.nav, 1)["pano"], "west")
        self.assertEqual(select_direction(self.nav, 1)["pano"], "north")
        self.assertEqual(start_move(self.nav, "confirm")[0]["target"], "north")

    def test_forward_uses_camera_even_after_highlighting_another_route(self):
        select_direction(self.nav, 1)
        select_direction(self.nav, 1)
        self.assertEqual(start_move(self.nav, "forward")[0]["target"], "east")

    def test_missing_selection_and_history_do_not_request_movement(self):
        self.assertIsNone(start_move(self.nav, "confirm")[0])
        self.assertIsNone(start_move(self.nav, "back")[0])

    def test_invalid_and_duplicate_links_are_filtered(self):
        update_navigation(self.nav, "start", 450, [make_route("start", 0), make_route("", 0),
                                       make_route("east", 90), make_route("east", 91)])
        self.assertEqual(self.nav["heading"], 90)
        self.assertEqual(self.nav["routes"], [make_route("east", 91)])
