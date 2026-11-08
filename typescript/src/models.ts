// Types de l'état du jeu reçu à chaque tour et des ordres à envoyer.

export type Direction = "N" | "S" | "E" | "O";
export type PlowType = "normal" | "big";

export interface Position {
  x: number;
  y: number;
}

export interface Plow {
  id: string;
  team: string;
  position: Position;
  type: PlowType;
  broken: boolean;
  load?: number; // absent pour les déneigeuses des autres équipes
}

export interface Call {
  id: string;
  position: Position;
  reward: number;
  expiresAt: number;
}

export interface GameMap {
  width: number;
  height: number;
  tiles: string[]; // tiles[y][x] : "." rue, "#" bâtiment, "D" dépôt, "G" garage
  snow: number[][]; // snow[y][x] : unités de neige
}

export interface Constants {
  maxTicks: number;
  tickMs: number;
  plowCapacity: number;
  plowCost: { normal: number; big: number };
  maxSnow: number;
  callRewardMin: number;
  callRewardMax: number;
  callDuration: number;
  snowfallPerTick: number;
  stormTicks: number; // tempête pendant les stormTicks derniers tours
  stormMultiplier: number; // neige et appels 311 multipliés pendant la tempête
}

export interface GameState {
  tick: number;
  you: string;
  money: number;
  garage: Position;
  plows: Plow[];
  map: GameMap;
  calls: Call[];
  errors: { plowId: string | null; reason: string }[];
  constants: Constants;
}

export type Action =
  | { plowId: string; type: "move"; direction: Direction }
  | { plowId: string; type: "unload" };

export interface Orders {
  actions: Action[];
  buy?: PlowType;
}

export function myPlows(state: GameState): Plow[] {
  return state.plows.filter((p) => p.team === state.you);
}
