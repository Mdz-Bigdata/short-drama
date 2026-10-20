export interface EpisodeGap {
  first: number;
  last: number;
  label: string;
}

export function normalizeMissingEpisodes(numbers: number[]): number[] {
  return [...new Set(numbers.filter(number => Number.isInteger(number) && number > 0 && number <= 200))]
    .sort((left, right) => left - right);
}

export function groupEpisodeGaps(numbers: number[]): EpisodeGap[] {
  const groups: EpisodeGap[] = [];
  for (const number of normalizeMissingEpisodes(numbers)) {
    const previous = groups.at(-1);
    if (previous && previous.last + 1 === number) {
      previous.last = number;
      previous.label = `${previous.first}–${number}`;
    } else {
      groups.push({ first: number, last: number, label: String(number) });
    }
  }
  return groups;
}
