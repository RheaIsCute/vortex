import unittest

from backend.scraper import split_rank_label


class RankLabelTests(unittest.TestCase):
    def test_current_henrikdev_labels_keep_tier_and_division(self):
        self.assertEqual(("ASCENDANT", "2"), split_rank_label("Ascendant 2"))
        self.assertEqual(("RADIANT", ""), split_rank_label("Radiant"))

    def test_missing_or_malformed_labels_are_safe(self):
        self.assertEqual(("", ""), split_rank_label(None))
        self.assertEqual(("", ""), split_rank_label("   "))

