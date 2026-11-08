// Votre bot. C'est le seul fichier que vous avez besoin de modifier.
//
// decide() est appelée à chaque tour avec l'état du jeu et doit retourner vos ordres.
// Pour l'instant, chaque déneigeuse se déplace au hasard.

import { Direction, GameState, Orders, myPlows } from "./models";

const DIRECTIONS: Direction[] = ["N", "S", "E", "O"];

export function decide(state: GameState): Orders {
  const orders: Orders = { actions: [] };
  for (const plow of myPlows(state)) {
    const direction = DIRECTIONS[Math.floor(Math.random() * DIRECTIONS.length)];
    orders.actions.push({ plowId: plow.id, type: "move", direction });
  }
  return orders;
}
