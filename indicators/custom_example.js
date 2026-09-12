/**
 * Mẫu chỉ báo viết bằng JavaScript
 * ==================================
 * Dùng khi bạn muốn kiểm soát hoàn toàn cách tính toán và vẽ.
 * Copy file này, đổi tên thành tên chỉ báo của bạn (vd: my_indicator.js).
 *
 * Cấu trúc bắt buộc: export object với các trường sau.
 */

const MyIndicator = {

  // Tên hiển thị trên nút toggle
  name: "Custom",

  // "overlay"  = vẽ chồng lên biểu đồ nến
  // "separate" = panel riêng bên dưới
  // "volume"   = vẽ chồng lên panel volume
  panel: "overlay",

  /**
   * Tính toán giá trị chỉ báo.
   *
   * @param {Array} data - Mảng các nến, mỗi phần tử là:
   *   { time: "2026-01-01", open, high, low, close, volume }
   *   Đã được sort theo time tăng dần.
   *
   * @returns {Array} Mảng các series để vẽ, mỗi series là:
   *   {
   *     label  : string,          // tên đường
   *     color  : string,          // màu hex
   *     width  : number,          // độ dày
   *     values : [{time, value}], // dữ liệu
   *     dashed : boolean,         // đường nét đứt (tùy chọn)
   *     type   : "line"|"histogram" // mặc định "line"
   *   }
   */
  compute(data) {
    // Ví dụ: tính WMA (Weighted Moving Average) 10 phiên
    const period = 10;
    const weights = Array.from({length: period}, (_, i) => i + 1);
    const weightSum = weights.reduce((a, b) => a + b, 0);

    const values = data.map((bar, i) => {
      if (i < period - 1) return { time: bar.time, value: null };
      const slice = data.slice(i - period + 1, i + 1);
      const wma = slice.reduce((sum, b, j) => sum + b.close * weights[j], 0) / weightSum;
      return { time: bar.time, value: parseFloat(wma.toFixed(2)) };
    }).filter(v => v.value !== null);

    return [
      {
        label : `WMA(${period})`,
        color : "#e879f9",
        width : 2,
        values: values,
        dashed: false,
        type  : "line",
      }
    ];
  },

  /**
   * (Tùy chọn) Tùy chỉnh cách render — bỏ qua nếu dùng render mặc định.
   * Chỉ cần khi bạn muốn dùng Lightweight Charts API trực tiếp.
   *
   * @param {Object} chart      - Instance LightweightCharts
   * @param {Object} mainSeries - Series nến chính
   * @param {Array}  results    - Kết quả từ compute()
   */
  // render(chart, mainSeries, results) {
  //   // Ví dụ tùy chỉnh nâng cao:
  //   const series = chart.addLineSeries({ color: results[0].color });
  //   series.setData(results[0].values);
  // }
};

// Bắt buộc: export để hệ thống nhận diện
if (typeof module !== 'undefined') module.exports = MyIndicator;
