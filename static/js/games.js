// games.js – palette pour les blocs jeux
window.gameColors = [
  'border-orange-500 bg-orange-500/20',
  'border-emerald-500 bg-emerald-500/20',
  'border-sky-500 bg-sky-500/20',
  'border-purple-500 bg-purple-500/20',
  'border-pink-500 bg-pink-500/20',
  'border-cyan-500 bg-cyan-500/20',
  'border-lime-500 bg-lime-500/20',
  'border-fuchsia-500 bg-fuchsia-500/20',
  'border-amber-500 bg-amber-500/20',
  'border-teal-500 bg-teal-500/20'
];

window.gameColorClass = function(idx){
  return window.gameColors[idx % window.gameColors.length];
};
