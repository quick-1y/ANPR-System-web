const INITIAL_STATE = {
  channels: [],
  lists: [],
  selectedListId: null,
  allEvents: [],
  lastPlatesByChannelId: {},
  plateLookup: {},
  currentEntries: [],
};

function cloneInitialState() {
  return {
    channels: [],
    lists: [],
    selectedListId: INITIAL_STATE.selectedListId,
    allEvents: [],
    lastPlatesByChannelId: {},
    plateLookup: {},
    currentEntries: [],
  };
}

export const state = cloneInitialState();
