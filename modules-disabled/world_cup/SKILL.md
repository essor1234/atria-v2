# world_cup

Data module created from uploaded files.

## When to use
- When the user asks about the datasets bundled in the world_cup module.

## Data
CSV datasets live in `<modules>/world_cup/data/` (original uploads such as .xlsx are kept alongside their converted .csv).

### Datasets
- `fifa-data/WorldCupMatches.csv` - 852 rows. Columns: Year, Datetime, Stage, Stadium, City, Home Team Name, Home Team Goals, Away Team Goals, Away Team Name, Win conditions, Attendance, Half-time Home Goals, Half-time Away Goals, Referee, Assistant 1, Assistant 2, RoundID, MatchID, Home Team Initials, Away Team Initials
- `fifa-data/WorldCupPlayers.csv` - 37784 rows. Columns: RoundID, MatchID, Team Initials, Coach Name, Line-up, Shirt Number, Player Name, Position, Event
- `fifa-data/WorldCups.csv` - 20 rows. Columns: Year, Country, Winner, Runners-Up, Third, Fourth, GoalsScored, QualifiedTeams, MatchesPlayed, Attendance

## How to use
Run the data explorer via the bash tool (`<modules>` resolves to the active modules directory - see the SKILL block header in the system prompt):
- `python <modules>/world_cup/scripts/data.py list` - datasets, row counts, columns
- `python <modules>/world_cup/scripts/data.py preview --file <file.csv> --limit 20`
- `python <modules>/world_cup/scripts/data.py query --file <file.csv> --filter <text> [--column <col>]`

The dashboard (`dashboard.html`) lists the datasets and renders any CSV as a sortable, filterable table. Hand-tailor it (domain KPIs, charts) by editing `dashboard.html`.
