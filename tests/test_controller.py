import sys
import unittest
from math import hypot
from types import SimpleNamespace
from unittest.mock import Mock, patch

from controller import (
    apply_dead_zone, close_controller, idle_input, map_input, new_input_state,
    normalize_axis, normalize_trigger, open_controller, poll_controller, raw_input,
)


class InputTests(unittest.TestCase):
    def test_dead_zone_removes_small_offsets_and_preserves_direction(self):
        self.assertEqual(apply_dead_zone(0.08, 0.10), (0.0, 0.0))
        self.assertEqual(apply_dead_zone(0.15, 0), (0.0, 0.0))
        x, y = apply_dead_zone(0.3, -0.4)
        self.assertAlmostEqual(x / y, -0.75)
        self.assertAlmostEqual(hypot(x, y), (0.5 - 0.15) / 0.85)
        self.assertAlmostEqual(hypot(*apply_dead_zone(1, 1)), 1)

    def test_signed_axis_normalization(self):
        self.assertEqual(normalize_axis(-32768), -1)
        self.assertEqual(normalize_axis(0), 0)
        self.assertEqual(normalize_axis(32767), 1)

    def test_trigger_normalization(self):
        self.assertEqual(normalize_trigger(-32768), 0)
        self.assertEqual(normalize_trigger(0), 0)
        self.assertAlmostEqual(normalize_trigger(16384), 0.5, places=4)
        self.assertEqual(normalize_trigger(32768), 1)

    def test_trigger_fires_once_until_release(self):
        mapper = new_input_state()
        map_input(mapper, raw_input())
        self.assertEqual(map_input(mapper, raw_input(forward=0.7))["actions"], {"forward"})
        self.assertFalse(map_input(mapper, raw_input(forward=0.55))["actions"])
        self.assertFalse(map_input(mapper, raw_input(forward=0.9))["actions"])
        self.assertFalse(map_input(mapper, raw_input(forward=0.2))["actions"])
        self.assertEqual(map_input(mapper, raw_input(forward=0.9))["actions"], {"forward"})

    def test_digital_and_pure_sideways_stick_actions_are_edges(self):
        mapper = new_input_state()
        map_input(mapper, raw_input())
        pressed = raw_input(left_x=-0.8, buttons=frozenset({"confirm"}))
        self.assertEqual(map_input(mapper, pressed)["actions"], {"previous", "confirm"})
        self.assertFalse(map_input(mapper, pressed)["actions"])
        self.assertEqual(map_input(mapper, raw_input(left_x=0.8))["actions"], {"next"})

    def test_left_stick_drives_and_right_stick_looks(self):
        mapper = new_input_state()
        self.assertFalse(map_input(mapper, raw_input(left_y=-1))["drive"])
        map_input(mapper, raw_input())
        forward = map_input(mapper, raw_input(left_y=-1, left_x=0.65, right_y=0.8))
        self.assertEqual(forward["actions"], {"drive_forward"})
        self.assertEqual(forward["drive"], "forward")
        self.assertEqual(forward["camera"][0], 0)
        self.assertGreater(forward["camera"][1], 0)
        self.assertEqual(map_input(mapper, raw_input(left_y=-0.45))["drive"], "forward")
        reverse = map_input(mapper, raw_input(left_y=0.9, right_x=-0.9))
        self.assertEqual(reverse["actions"], {"drive_back"})
        self.assertEqual(reverse["drive"], "back")
        self.assertLess(reverse["camera"][0], 0)

    def test_disconnect_clears_axes_and_suppresses_held_input_on_reconnect(self):
        mapper = new_input_state()
        map_input(mapper, raw_input())
        self.assertEqual(map_input(mapper, raw_input(back=1))["actions"], {"back"})
        self.assertEqual(map_input(mapper, None), idle_input())
        self.assertFalse(map_input(mapper, raw_input(back=1))["actions"])
        map_input(mapper, raw_input())
        self.assertEqual(map_input(mapper, raw_input(back=1))["actions"], {"back"})


class ReaderTests(unittest.TestCase):
    def test_device_removal_and_reconnection(self):
        pad = Mock()
        pad.attached.return_value = True
        pad.get_axis.return_value = 0
        pad.get_button.return_value = False
        sdl = Mock()
        sdl.get_count.return_value = 1
        sdl.is_controller.return_value = True
        sdl.name_forindex.return_value = "DualSense"
        sdl.Controller.return_value = pad

        pygame = Mock()
        pygame.error = RuntimeError
        with patch.dict(sys.modules, {
            "pygame": pygame, "pygame._sdl2": SimpleNamespace(controller=sdl),
        }), patch("controller.monotonic") as clock:
            clock.return_value = 1
            reader = open_controller()
            poll_controller(reader)
            self.assertEqual(reader["name"], "DualSense")

            pygame.CONTROLLER_BUTTON_BACK = 4
            pad.get_button.side_effect = lambda code: code == pygame.CONTROLLER_BUTTON_BACK
            self.assertNotIn("map", poll_controller(reader)["actions"])
            pad.get_button.side_effect = lambda code: code == 20  # SDL touchpad click
            self.assertIn("map", poll_controller(reader)["actions"])
            self.assertNotIn("map", poll_controller(reader)["actions"])
            pad.get_button.side_effect = None

            pad.attached.return_value = False
            sdl.get_count.return_value = 0
            clock.return_value = 2
            self.assertEqual(poll_controller(reader), idle_input())
            self.assertEqual(reader["name"], "")
            pad.quit.assert_called_once()

            pad.attached.return_value = True
            sdl.get_count.return_value = 1
            clock.return_value = 3
            poll_controller(reader)
            self.assertEqual(reader["name"], "DualSense")
            close_controller(reader)
            pygame.quit.assert_called_once()
