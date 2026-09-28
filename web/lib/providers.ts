// App connectors shown in onboarding and on the landing page. Storage keys map to CareProfile.connectors.

export type Key = "doordash" | "uber" | "groceries" | "taskrabbit" | "gmail" | "bank";

export const PROVIDERS: {
  key: Key;
  name: string;
  logo: string;
  color: string;
  does: string;
  bullets: string[];
}[] = [
  {
    key: "groceries",
    name: "Instacart",
    logo: "https://cdn.simpleicons.org/instacart/43B02A",
    color: "#43B02A",
    does: "get groceries",
    bullets: ["Restock essentials from the usual store", "Reads every item and the total back first", "Large or new orders wait for your okay"],
  },
  {
    key: "uber",
    name: "Uber",
    logo: "https://cdn.simpleicons.org/uber/000000",
    color: "#000000",
    does: "book rides",
    bullets: ["Book a ride to the doctor or the pharmacy", "Says the car and driver out loud when it's on the way", "You get a message with every trip"],
  },
  {
    key: "doordash",
    name: "DoorDash",
    logo: "https://cdn.simpleicons.org/doordash/FF3008",
    color: "#FF3008",
    does: "order food",
    bullets: ["Order dinner, or \"the usual\", by phone", "Reads the order and total back before placing it", "Anything unusual waits for your okay"],
  },
  {
    key: "taskrabbit",
    name: "TaskRabbit",
    logo: "/brands/taskrabbit.svg",
    color: "#00A86B",
    does: "book home help",
    bullets: ["A plumber, handyman, or cleaner from a plain description of the problem", "Reads the tasker, price, and time back before booking", "Anyone new or over the limit waits for your okay"],
  },
  {
    key: "gmail",
    name: "Gmail",
    logo: "https://cdn.simpleicons.org/gmail/EA4335",
    color: "#EA4335",
    does: "spot bills and scams",
    bullets: ["Finds bills and appointment emails for the morning check-in", "Flags emails that look like scams before anyone acts on them", "Gary reads summaries, never sends email"],
  },
  {
    key: "bank",
    name: "your bank",
    logo: "/brands/bank.svg",
    color: "#1f3d34",
    does: "pay the bills you approve",
    bullets: ["Pays known bills after reading the amount back", "Anything over the limit or to someone new waits for your okay", "Nothing moves without a spoken yes on the call"],
  },
];
