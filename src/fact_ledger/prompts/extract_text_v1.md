# Read the figures in a saved text: a press article or an interview note

The user message is the text of one file. Each paragraph is under a marker `[para N]`, with N from 1. The text is prose: a paragraph states a figure in a sentence, not in a table.

Return one `TextExtraction` JSON object: `values`. Every field of every object is required.

## Your job
You read. You copy what the text prints. The code does the rest.
- Do not map a label to a metric id. The only exception is `candidate_metric_ids` below.
- Do not give a value, a precision, an as-of date or a published date.
- Do not calculate. Do not multiply by 12, add, subtract or calculate growth.
- Report each figure as printed, also when it disagrees with another figure. Do not correct, average or merge figures.
- Do not use outside knowledge. Use only what the text prints.

## Which figures
Give one object in `values` for each figure that the text states as the value of a metric of the company, also when its period is unclear. Use the reading order.

Ignore these numbers: dates, ages, addresses and numbers that are part of a name or a label ("Top 10 customers").

**Give no object for a change figure.** A change figure states the movement of another figure: "grew 40%", "up 12% on last year", "+2.1 points". Keep the amounts that it compares, when the text prints them.

**A metric that compares two periods is still a value.** "Net revenue retention of 112%" is a value.

## Fields of each value
**`paragraph`**: the N of the `[para N]` marker of the paragraph that prints the figure. Never guess.

**`stated_label`**: the label words as the text prints them, with the same case, spelling and punctuation. Do not rewrite, shorten or complete them.
- A label is a noun phrase of the sentence: "annual recurring revenue", "paying customers". When an abbreviation in brackets follows the words ("annual recurring revenue (ARR)"), copy the words only. Copy an abbreviation when the text prints no words for it.
- Remove the figure, with its currency, its scale word and its approximation word.
- Remove a date or period: "at the end of 2024", "in 2023", "in the third quarter".
- Remove a segment, region, group or basis marker, as you remove a period. The fields `segment`, `region` and `basis` below take it. Keep the marker when the whole label with the marker is an alias in the metric dictionary below.
- Keep all other words.

**`printed`**: the number exactly as the text prints it, as one unbroken piece of the paragraph. Keep the currency symbol or code, a scale letter that follows the number ("k", "m", "bn"), "%" and "x". Write a scale word ("million", "thousand", "billion", the "M" of "MEUR") as its letter in `scale`, never in `printed`.
- "€8.1 million" gives `printed` "€8.1" and `scale` "m". "8.1 MEUR" gives "8.1", "m" and `unit` "EUR". "€675k" gives "€675k" and "k". "12 per cent" gives "12" and `unit` "percent".
- An approximation word ("about", "around", "roughly", "approximately", "some") is not part of `printed`. It changes no other field.
- A bound word is "more than", "over", "at least", "almost", "nearly", "up to" or "below". A bound word marks a bound, not a point value. Keep the bound word in `printed`. "over €8 million" gives `printed` "over €8" and `scale` "m".

**`scale`**: "k", "m" or "bn" from the scale letter or word of the figure. "" if the text shows no scale.

**`unit`**:
- Money: the currency symbol or ISO code as the text prints it: "€", "£", "$$", "EUR", "SEK". Do not change a symbol into a code. If the text shows no currency for a money value, give "". Do not guess.
- "percent" for a figure with "%" or "per cent". "ratio" for a multiple such as "4.5x". "count" for a number of things (customers, users, employees).

**`period_type`, `period_start`, `period_end`**: from the date that the paragraph of the figure prints for this value. Use ISO dates.
- Never guess a period. Set `period_start` and `period_end` to null when the paragraph prints no year for the value, or you cannot tell which printed date belongs to it. A year in another paragraph does not date this value.
- Set them to null for a relative period: "last year", "this year", "last quarter", "to date", "now", "currently", "today". Never resolve it from the date of the article. Set them to null for a stock in the present tense with no printed date ("Nimbus has 190 customers").
- Set them to null for a forecast, a plan or a target: "expects €10m by 2026", "on track for", "aims to reach", "budget of €2m".
- A year-to-date period ("first half of 2025", "nine months to September 2025"): `ytd`, from the first day of the financial year to the last day of the last month that the period covers. "The second half of 2024": `half`, the last 6 months of the financial year.
- A day, or "the end of <year>", "the end of <month year>": `point_in_time`, start and end on that day. "at the end of 2024" gives 2024-12-31.
- A month, quarter or year only, and the whole `stated_label` is an alias of a `stock` metric that is not an umbrella (a level at one moment: ARR, MRR, paying customers, registered users, licensed seats, backlog): `point_in_time` on the last day of that period.
- A month, quarter or year only, and any other label (a flow, an umbrella alias, or a label that is not an alias): the period follows the printed words. "in 2023" gives `fy`, 2023-01-01 to 2023-12-31. "in the fourth quarter of 2024" gives `quarter`, 2024-10-01 to 2024-12-31. "in December 2024" gives `month`, 2024-12-01 to 2024-12-31.
- "LTM" or "TTM", or "the last twelve months to <month year>": `ttm`, the 12 months that end on the last day of that month.
- A two-digit year means 20YY. Use calendar years, unless the text states a different financial year end.

**`candidate_metric_ids`**: an empty list, with one exception.
- The exception: the whole `stated_label` equals an alias of an umbrella metric (an id that ends in `_unspecified`). Upper and lower case do not matter. Then list the "Usual candidates" of that umbrella from its definition note, in the order of the note. Remove a candidate only when the text excludes it. List only metric ids of the dictionary, and never an umbrella id.
- A label with more words is not the alias inside it.

**`segment`, `region` and `basis`**: the qualifier of the figure. Give "" for a field that the text does not state.
- `segment` is a part of the company that is not a geography: a business unit, a division, a product line, a customer type or a sales channel.
- `region` is a geography of any size: a continent, a group of countries, a country or a city.
- Write each marker as the text prints it. Do not translate it, shorten it or join two names.
- "Group", "Consolidated" and "Total group" mark the figure of the whole company. Take the marker out of the label, and give "" for `segment` and for `region`.
- `basis` has three values: "reported", "pro_forma" and "constant_currency". Write one of them for the matching printed words, or "". Do not write "reported" for a figure that prints no basis word. For "organic", "like-for-like" or "LFL", write that word exactly as printed. Every other word stays in `stated_label`.

## Metric dictionary
One line for each metric: id, canonical name, stock or flow, aliases, definition note.

$dictionary
