"""
Stat Scraper & Official Valorant API Integration module.
Uses HenrikDev API with user API key to fetch:
- Account Level & Player Card
- Live Current Rank & RR
- All-Time Peak Rank & Season
- Recent 10 Match History
"""

import aiohttp
import urllib.parse
from typing import Dict, Any, Optional, List

REGION_MAP = {
    "NA": "na",
    "EU": "eu",
    "AP": "ap",
    "KR": "kr",
    "BR": "br",
    "LATAM": "latam"
}

# Current Episode Valorant API Competitive Tier Index mapping
TIER_INDEX_MAP = {
    "UNRANKED": 0,
    "IRON 1": 3, "IRON 2": 4, "IRON 3": 5,
    "BRONZE 1": 6, "BRONZE 2": 7, "BRONZE 3": 8,
    "SILVER 1": 9, "SILVER 2": 10, "SILVER 3": 11,
    "GOLD 1": 12, "GOLD 2": 13, "GOLD 3": 14,
    "PLATINUM 1": 15, "PLATINUM 2": 16, "PLATINUM 3": 17,
    "DIAMOND 1": 18, "DIAMOND 2": 19, "DIAMOND 3": 20,
    "ASCENDANT 1": 21, "ASCENDANT 2": 22, "ASCENDANT 3": 23,
    "IMMORTAL 1": 24, "IMMORTAL 2": 25, "IMMORTAL 3": 26,
    "RADIANT": 27
}

TIER_BASE_URL = "https://media.valorant-api.com/competitivetiers/03621f52-342b-cf4e-4f86-9350a49c6d04"


def get_official_rank_icon(tier: str, division: str = "") -> str:
    """Returns direct official Valorant API high-res rank icon URL."""
    tier_upper = (tier or "UNRANKED").upper().strip()
    div_str = (division or "").strip()
    
    if tier_upper in ("UNRANKED", "RADIANT") or not div_str:
        key = tier_upper
    else:
        key = f"{tier_upper} {div_str}"
        
    tier_idx = TIER_INDEX_MAP.get(key)
    if tier_idx is None:
        tier_idx = TIER_INDEX_MAP.get(f"{tier_upper} 1", 0)
        
    return f"{TIER_BASE_URL}/{tier_idx}/largeicon.png"


class StatScraper:
    def __init__(self, riot_api_key: Optional[str] = ""):
        # API keys are user-provided settings, never application defaults.
        self.riot_api_key = riot_api_key or ""

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        if self.riot_api_key:
            headers["Authorization"] = self.riot_api_key
        return headers

    async def fetch_account_stats(self, display_name: str, region: str = "NA") -> Dict[str, Any]:
        """
        Fetches live Valorant statistics, level, rank emblems, peak rank,
        and recent 10 match history for any Riot ID (Name#TAG) over the web.
        """
        result = {
            "peak_rank_tier": "",
            "peak_rank_division": "",
            "peak_rank_icon_url": "",
            "peak_rank_season": "",
            "card_small_url": "",
            "top_champs": []
        }

        if not display_name or "#" not in display_name:
            return result

        name, tag = display_name.strip().split("#", 1)
        region_code = REGION_MAP.get((region or "NA").upper(), "na")
        enc_name = urllib.parse.quote(name.strip())
        enc_tag = urllib.parse.quote(tag.strip())
        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            # 1. Fetch Account Info (Exact Level, Real Region & Player Card)
            try:
                acc_url = f"https://api.henrikdev.xyz/valorant/v1/account/{enc_name}/{enc_tag}"
                async with session.get(acc_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        acc_data = data.get("data", {})
                        if acc_data:
                            # Only set "level" when the API actually returned
                            # one - an absent key means "no data", so callers
                            # keep whatever level is already stored instead of
                            # clobbering it with a bogus 1 on a rate-limit.
                            acc_level = acc_data.get("account_level")
                            if isinstance(acc_level, int) and acc_level > 0:
                                result["level"] = acc_level
                            detected_reg = (acc_data.get("region") or "").upper()
                            if detected_reg in REGION_MAP:
                                result["region"] = detected_reg
                                region_code = REGION_MAP[detected_reg]

                            card_info = acc_data.get("card", {})
                            if card_info:
                                result["card_small_url"] = card_info.get("small", "") or card_info.get("wide", "")
            except Exception:
                pass

            # 2. Fetch MMR & Peak Rank
            try:
                mmr_url = f"https://api.henrikdev.xyz/valorant/v2/mmr/{region_code}/{enc_name}/{enc_tag}"
                async with session.get(mmr_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        mmr_data = data.get("data", {})
                        if mmr_data:
                            # Current rank
                            curr_data = mmr_data.get("current_data", {})
                            if curr_data:
                                curr_tier_patched = curr_data.get("currenttierpatched", "Unranked")
                                parts = curr_tier_patched.split()
                                if parts:
                                    result["rank_tier"] = parts[0].upper()
                                    result["rank_division"] = parts[1] if len(parts) >= 2 else ""
                                    result["lp"] = curr_data.get("ranking_in_tier", 0)
                                    result["games_played"] = curr_data.get("games_needed_for_rating", 0)

                            # Peak rank
                            peak_data = mmr_data.get("highest_rank", {})
                            if peak_data:
                                peak_patched = peak_data.get("patched_tier", "")
                                if peak_patched:
                                    p_parts = peak_patched.split()
                                    if len(p_parts) >= 1:
                                        result["peak_rank_tier"] = p_parts[0].upper()
                                    if len(p_parts) >= 2:
                                        result["peak_rank_division"] = p_parts[1]
                                    result["peak_rank_season"] = peak_data.get("season", "")
            except Exception:
                pass

            # 3. Fetch Recent Match History (up to 10 matches)
            try:
                matches_url = f"https://api.henrikdev.xyz/valorant/v3/matches/{region_code}/{enc_name}/{enc_tag}?size=10"
                async with session.get(matches_url, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        raw_matches = data.get("data", [])
                        parsed_matches = self._parse_matches(raw_matches, name, tag)
                        if parsed_matches:
                            result["match_history"] = parsed_matches
                            wins = sum(1 for m in parsed_matches if m.get("outcome") == "VICTORY")
                            result["winrate"] = round((wins / len(parsed_matches)) * 100, 1)
                            result["games_played"] = len(parsed_matches)
            except Exception:
                pass

        # Generate official rank icon URLs - only for ranks this call actually
        # resolved, so a failed lookup can't replace a stored emblem with the
        # unranked one.
        if result.get("rank_tier"):
            result["rank_icon_url"] = get_official_rank_icon(
                result["rank_tier"], result.get("rank_division", "")
            )
        if result["peak_rank_tier"]:
            result["peak_rank_icon_url"] = get_official_rank_icon(result["peak_rank_tier"], result["peak_rank_division"])

        return result

    def _parse_matches(self, raw_matches: List[Dict[str, Any]], target_name: str, target_tag: str) -> List[Dict[str, Any]]:
        """Parses HenrikDev raw match data into clean UI match cards."""
        matches = []
        target_name_lower = target_name.lower().strip()
        target_tag_lower = target_tag.lower().strip()

        for m in raw_matches:
            try:
                metadata = m.get("metadata", {})
                players = m.get("players", {}).get("all_players", [])
                teams = m.get("teams", {})

                # Locate target player in match
                player_obj = None
                for p in players:
                    p_name = (p.get("name") or "").lower().strip()
                    p_tag = (p.get("tag") or "").lower().strip()
                    if p_name == target_name_lower and p_tag == target_tag_lower:
                        player_obj = p
                        break
                    elif p_name == target_name_lower:
                        player_obj = p
                        break

                if not player_obj:
                    continue

                player_team = (player_obj.get("team") or "Red").lower()
                other_team = "blue" if player_team == "red" else "red"

                team_data = teams.get(player_team, {})
                enemy_data = teams.get(other_team, {})

                rounds_won = team_data.get("rounds_won", 0)
                rounds_lost = team_data.get("rounds_lost", 0) or enemy_data.get("rounds_won", 0)
                has_won = team_data.get("has_won", False)

                if has_won:
                    outcome = "VICTORY"
                elif rounds_won == rounds_lost and rounds_won > 0:
                    outcome = "DRAW"
                else:
                    outcome = "DEFEAT"

                stats = player_obj.get("stats", {})
                kills = stats.get("kills", 0)
                deaths = stats.get("deaths", 0)
                assists = stats.get("assists", 0)
                score = stats.get("score", 0)
                headshots = stats.get("headshots", 0)
                bodyshots = stats.get("bodyshots", 0)
                legshots = stats.get("legshots", 0)
                total_shots = headshots + bodyshots + legshots
                hs_pct = round((headshots / total_shots) * 100) if total_shots > 0 else 0

                kdr = round(kills / max(deaths, 1), 2)

                char_name = player_obj.get("character", "Jett")
                assets = player_obj.get("assets", {}).get("agent", {})
                agent_icon = assets.get("small", "") or assets.get("bust", "") or "https://media.valorant-api.com/agents"

                map_name = metadata.get("map", "Ascent")
                mode = metadata.get("mode", "Competitive")
                game_start = metadata.get("game_start_patched", "") or metadata.get("game_start", "")

                roster = []
                for participant in players:
                    participant_stats = participant.get("stats", {}) or {}
                    participant_agent = participant.get("assets", {}).get("agent", {}) or {}
                    participant_name = participant.get("name", "") or "Unknown"
                    participant_tag = participant.get("tag", "") or ""
                    participant_score = int(participant_stats.get("score", 0) or 0)
                    participant_rounds = max(1, int(participant_stats.get("rounds", 0) or (rounds_won + rounds_lost) or 1))
                    participant_head = int(participant_stats.get("headshots", 0) or 0)
                    participant_body = int(participant_stats.get("bodyshots", 0) or 0)
                    participant_leg = int(participant_stats.get("legshots", 0) or 0)
                    participant_shots = participant_head + participant_body + participant_leg
                    participant_damage = int(participant_stats.get("damage_made", 0) or 0)
                    raw_team = participant.get("team", "") or ""
                    team_clean = raw_team.title() if raw_team else ("Blue" if player_team == "blue" else "Red")
                    roster.append({
                        "puuid": participant.get("puuid", "") or "",
                        "riot_id": f"{participant_name}#{participant_tag}" if participant_tag else participant_name,
                        "name": f"{participant_name}#{participant_tag}" if participant_tag else participant_name,
                        "team": team_clean,
                        "is_self": (
                            participant_name.lower().strip() == target_name_lower
                            and (not target_tag_lower or participant_tag.lower().strip() == target_tag_lower)
                        ),
                        "agent": participant.get("character", ""),
                        "agent_icon": participant_agent.get("small", "") or participant_agent.get("bust", ""),
                        "kills": participant_stats.get("kills", 0),
                        "deaths": participant_stats.get("deaths", 0),
                        "assists": participant_stats.get("assists", 0),
                        "score": participant_score,
                        "acs": round(participant_score / participant_rounds),
                        "damage": participant_damage,
                        "adr": round(participant_damage / participant_rounds),
                        "hs_pct": round(participant_head / participant_shots * 100, 1)
                                  if participant_shots else 0.0,
                    })

                team_summaries = []
                for team_name, summary in teams.items():
                    summary = summary or {}
                    team_summaries.append({
                        "team": str(team_name).title(),
                        "rounds_won": int(summary.get("rounds_won", 0) or 0),
                        "won": bool(summary.get("has_won", False)),
                    })

                matches.append({
                    "match_id": metadata.get("matchid", ""),
                    "map": map_name,
                    "mode": mode,
                    "outcome": outcome,
                    "rounds_won": rounds_won,
                    "rounds_lost": rounds_lost,
                    "agent": char_name,
                    "agent_icon": agent_icon,
                    "kills": kills,
                    "deaths": deaths,
                    "assists": assists,
                    "kdr": kdr,
                    "score": score,
                    "hs_pct": hs_pct,
                    "game_date": game_start,
                    "teams": team_summaries,
                    "round_results": [],
                    "roster": roster
                })
            except Exception:
                continue

        return matches[:10]
