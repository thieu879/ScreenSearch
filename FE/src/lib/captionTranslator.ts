/**
 * Utility to translate Florence-2 AI frame captions into Vietnamese when UI language is 'vi'.
 * Preserves exact English string when UI language is 'en'.
 */

export function translateCaption(caption?: string, lang: string = 'vi'): string {
  if (!caption) return '';
  if (lang === 'en') return caption;

  let translated = caption;

  const replacements: [RegExp, string][] = [
    [/The image shows/gi, 'Hình ảnh hiển thị'],
    [/This image shows/gi, 'Hình ảnh này hiển thị'],
    [/An image of/gi, 'Hình ảnh về'],
    [/A photograph of/gi, 'Bức ảnh chụp'],
    [/a white car/gi, 'một chiếc ô tô màu trắng'],
    [/a black car/gi, 'một chiếc ô tô màu đen'],
    [/a red car/gi, 'một chiếc ô tô màu đỏ'],
    [/a blue car/gi, 'một chiếc ô tô màu xanh dương'],
    [/a silver car/gi, 'một chiếc ô tô màu bạc'],
    [/a yellow car/gi, 'một chiếc ô tô màu vàng'],
    [/a grey car|a gray car/gi, 'một chiếc ô tô màu xám'],
    [/a car/gi, 'một chiếc ô tô'],
    [/cars/gi, 'các chiếc ô tô'],
    [/a white vehicle/gi, 'một phương tiện màu trắng'],
    [/a vehicle/gi, 'một phương tiện'],
    [/vehicles/gi, 'các phương tiện giao thông'],
    [/a bus/gi, 'một xe buýt'],
    [/a truck/gi, 'một xe tải'],
    [/a van/gi, 'một xe bán tải'],
    [/a motorcycle/gi, 'một xe máy'],
    [/a bicycle/gi, 'một xe đạp'],
    [/cyclists/gi, 'người đi xe đạp'],
    [/a cyclist/gi, 'người đi xe đạp'],
    [/pedestrians/gi, 'người đi bộ'],
    [/pedestrian/gi, 'người đi bộ'],
    [/driving down a street/gi, 'đang di chuyển trên đường phố'],
    [/driving down a road/gi, 'đang di chuyển trên đường'],
    [/driving on a street/gi, 'đang di chuyển trên phố'],
    [/driving on a road/gi, 'đang di chuyển trên đường'],
    [/driving on/gi, 'đang di chuyển trên'],
    [/parked on/gi, 'đang đỗ trên'],
    [/parked along/gi, 'đang đỗ dọc theo'],
    [/lined with trees/gi, 'hai bên rợp bóng cây'],
    [/with buildings on either side/gi, 'với các tòa nhà ở hai bên'],
    [/with buildings in the background/gi, 'với các tòa nhà ở phía sau'],
    [/and a clear blue sky/gi, 'và bầu trời xanh quang đãng'],
    [/under clear daytime skies/gi, 'dưới bầu trời ban ngày quang đãng'],
    [/under clear skies/gi, 'dưới bầu trời quang đãng'],
    [/clear blue sky/gi, 'bầu trời xanh quang đãng'],
    [/in the background/gi, 'ở phía sau'],
    [/on the road/gi, 'trên đường'],
    [/on the street/gi, 'trên phố'],
    [/traffic lights/gi, 'đèn giao thông'],
    [/traffic light/gi, 'đèn giao thông'],
    [/crosswalk/gi, 'vạch kẻ đường cho người đi bộ'],
    [/intersection/gi, 'ngã tư giao lộ'],
    [/at night/gi, 'vào ban đêm'],
    [/during the day/gi, 'vào ban ngày'],
    [/in wet conditions/gi, 'trong điều kiện đường ướt'],
    [/rainy weather/gi, 'thời tiết mưa'],
  ];

  for (const [pattern, replacement] of replacements) {
    translated = translated.replace(pattern, replacement);
  }

  return translated;
}
