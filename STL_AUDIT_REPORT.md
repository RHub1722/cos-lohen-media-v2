# Независимая проверка шести STL-файлов накладок копья

## Исходные файлы

Проверены:

- `spear_7_L.stl`
- `spear_7_R.stl`
- `spear_9_L.stl`
- `spear_9_R.stl`
- `spear_10_L.stl`
- `spear_10_R.stl`

Единицы STL приняты за миллиметры согласно заявленным габаритам. Сам STL единицы измерения не хранит.

## Методика

Использованы:

- Python 3.12.10
- NumPy 2.4.6
- trimesh 5.0.0
- SciPy 1.17.1

Проверены:

1. Bounds и габариты.
2. Знаковый объём независимой тетраэдральной суммой.
3. Площадь поверхности и площади отдельных треугольников.
4. Инцидентность рёбер после сварки совпадающих вершин с точностью `1e-6` мм.
5. Дубли граней и неманифолдные рёбра.
6. Фактический контакт со столом.
7. Зеркальность L/R по множествам вершин.
8. Возможность совместить L/R собственным вращением с определителем `+1`.
9. Укладка как bounding rectangle и отдельно укладка реального XY-контура STL.
10. Приближённая масса через площадь оболочки и объём.

## 1. Габариты и объём

Формат ячеек: `заявлено → измерено (расхождение)`.

| Файл | X, мм | Y, мм | Z, мм | Знаковый объём, см³ |
|---|---:|---:|---:|---:|
| spear_7_L | 53.3 → 53.3378 (+0.071%) | 251.0 → 251.0497 (+0.020%) | 94.7 → 94.7403 (+0.043%) | 132 → +132.4035 (+0.306%) |
| spear_7_R | 53.3 → 53.3378 (+0.071%) | 251.0 → 251.0497 (+0.020%) | 94.7 → 94.7403 (+0.043%) | 132 → +132.4035 (+0.306%) |
| spear_9_L | 97.5 → 97.4703 (−0.031%) | 232.4 → 232.3500 (−0.022%) | 134.7 → 134.7117 (+0.009%) | 155 → +154.7026 (−0.192%) |
| spear_9_R | 97.5 → 97.4703 (−0.031%) | 232.4 → 232.3500 (−0.022%) | 134.7 → 134.7117 (+0.009%) | 155 → +154.7026 (−0.192%) |
| spear_10_L | 45.8 → 45.8450 (+0.098%) | 130.1 → 130.1398 (+0.031%) | 150.6 → 150.5926 (−0.005%) | 87 → +86.9459 (−0.062%) |
| spear_10_R | 45.8 → 45.8450 (+0.098%) | 130.1 → 130.1398 (+0.031%) | 150.6 → 150.5926 (−0.005%) | 87 → +86.9459 (−0.062%) |

Расхождений больше 1% нет.

В каждой паре L/R габариты совпадают численно, не только до сотых. Центры bounding box по X и Y равны нулю, минимальный Z равен нулю.

При этом `min Z = 0` не означает, что деталь действительно устойчиво лежит на столе — см. отдельную находку ниже.

## 2. Зеркалирование L/R

После отражения всех уникальных вершин L по X:

\[
(x,y,z)\rightarrow(-x,y,z)
\]

множество вершин в точности совпадает с R при округлении координат до `1e-6` мм.

| Пара | RMS ошибки отражения | Максимальная ошибка |
|---|---:|---:|
| spear_7 | 0 мм | 0 мм |
| spear_9 | 0 мм | 0 мм |
| spear_10 | 0 мм | 0 мм |

Сырые треугольники R также в точности получаются из L отражением X и перестановкой второй и третьей вершин каждого треугольника. Перестановка исправляет обход после отражения, поэтому знаковый объём R остаётся положительным.

Проверена гипотеза, что R может быть не зеркалом, а собственным вращением L. Поскольку ковариационные собственные значения у деталей различны, любое точное жёсткое совмещение должно переводить соответствующие главные оси друг в друга. Перебраны все допустимые варианты знаков главных осей с определителем вращения `+1`.

Лучшие найденные собственные вращения:

| Пара | RMS, мм | Максимальная ошибка, мм |
|---|---:|---:|
| spear_7 | 0.3837 | 2.893 |
| spear_9 | 6.520 | 20.539 |
| spear_10 | 8.270 | 31.549 |

Нулевая ошибка получается только у отражения, но не у собственного вращения.

## 3. Находки по убыванию практической стоимости ошибки

### 3.1. Детали фактически не поставлены на стол

Это самая существенная проблема подготовки.

У каждого из шести файлов:

- на `Z = 0` находится ровно одна уникальная вершина;
- полностью лежащих на `Z = 0` треугольников нет;
- площадь плоского контакта со столом равна нулю.

Площадь горизонтального сечения на высоте первого слоя 0.2 мм:

| Деталь | Площадь сечения на Z=0.2 мм |
|---|---:|
| spear_7 | 0.425 мм² |
| spear_9 | 0.679 мм² |
| spear_10 | 2.604 мм² |

То есть детали начинаются практически с точки. Для TPU 95A это крайне ненадёжная ориентация:

- первый слой будет микроскопическим;
- деталь не имеет устойчивого собственного основания;
- brim не исправит отсутствие нормального первого контура автоматически;
- вероятны отрыв, качание или необходимость большого объёма поддержек.

Перед печатью нужно сделать одно из следующего:

- выбрать другую ориентацию с реальной плоской опорой;
- выполнить плоский срез основания;
- спроектировать технологическую подставку;
- проверить raft/support в слайсере.

Простой сдвиг модели до `min Z = 0` нельзя считать корректной постановкой на стол.

### 3.2. Методика расчёта массы непереносима между деталями

Коэффициент:

\[
0.36=\frac{1210}{2680\cdot1.24}
\]

является средним эмпирическим коэффициентом всего копья. Он одновременно включает:

- соотношение поверхности и объёма разных деталей;
- локальные толщины;
- оболочки;
- заполнение;
- верхние и нижние слои;
- возможные сплошные зоны.

Применять его к отдельной детали как универсальную долю материала нельзя. Подробный пересчёт массы приведён в разделе 6.

### 3.3. `spear_7` и `spear_10` не являются корректными 2-manifold объёмами

После сварки совпадающих вершин:

| Файлы | Открытые рёбра | Неманифолдные рёбра | Группы дублированных граней | `trimesh.is_volume` |
|---|---:|---:|---:|---:|
| spear_7_L/R | 0 | 3 | 3 | False |
| spear_9_L/R | 0 | 0 | 0 | True |
| spear_10_L/R | 0 | 2 | 2 | False |

Таким образом, утверждение «открытых рёбер ноль» формально верно, но недостаточно для заключения, что сетка является корректным замкнутым телом.

У `spear_7` и `spear_10` имеются наложенные грани. Рёбра этих граней имеют инцидентность больше двух, поэтому поверхность не является 2-manifold.

Дублированные грани очень малы и почти не влияют на численный объём, однако могут:

- запускать автоматический mesh repair в слайсере;
- давать разные результаты в разных слайсерах;
- создавать локальные артефакты контуров;
- мешать корректным булевым операциям.

Перед производственной печатью `spear_7` и `spear_10` следует отремонтировать и проверить повторно.

У `spear_9` есть один строго нулевой треугольник. В исходной топологии его рёбра участвуют в замыкании поверхности. Простое удаление этого треугольника создаёт вырожденную трёхрёберную границу, поэтому после удаления требуется повторное замыкание/ретриангуляция.

### 3.4. Микротреугольников больше двух, и они есть во всех моделях

Для воспроизводимости «почти вырожденным» принят треугольник площадью меньше:

\[
10^{-6}\text{ мм}^2
\]

Результат для каждого отдельного файла:

| Файл пары | Медианная площадь, мм² | Минимальная площадь, мм² | Количество `<1e-6` | Строго нулевых |
|---|---:|---:|---:|---:|
| spear_7_L или R | 0.168789 | 5.65e−8 | 1 | 0 |
| spear_9_L или R | 0.500192 | 0 | 4 | 1 |
| spear_10_L или R | 0.563628 | 4.29e−9 | 4 | 0 |

В `spear_10` четыре таких треугольника:

- `4.2873e-9` мм²
- `2.2110e-7` мм²
- `2.7861e-7` мм²
- `3.1256e-7` мм²

Следовательно, заявление «в `spear_10` два треугольника около `1e-7` мм²» не подтвердилось.

По всем шести файлам суммарно:

- `spear_7_L/R`: 2 микротреугольника;
- `spear_9_L/R`: 8;
- `spear_10_L/R`: 8.

### 3.5. Формула укладки по диагонали неверна как универсальное правило

Для прямоугольника `L×W`, где `L ≥ W`, при `0 ≤ θ ≤ 45°`:

\[
B_x=L\cos\theta+W\sin\theta
\]

\[
B_y=L\sin\theta+W\cos\theta
\]

На этом интервале `B_x ≥ B_y`, поэтому минимизируется `B_x`. Функция `B_x` вогнута, следовательно, минимум находится на одном из концов интервала: при `0°` или `45°`.

Итог:

\[
\min_\theta\max(B_x,B_y)=\min\left(L,\frac{L+W}{\sqrt2}\right)
\]

Угол `45°` оптимален только если:

\[
\frac{L}{W}>1+\sqrt2\approx2.4142
\]

Если отношение меньше, оптимально не вращать прямоугольник.

Условие помещения прямоугольника в квадрат со стороной `S`:

\[
L\le S \quad\text{или}\quad L+W\le S\sqrt2
\]

Проверка bounding rectangle:

| Деталь | L/W | При 0° | При 45° | Оптимум прямоугольника |
|---|---:|---:|---:|---:|
| spear_7 | 4.7068 | 251.050 мм | 215.234 мм | 45°, 215.234 мм |
| spear_9 | 2.3838 | 232.350 мм | 233.218 мм | 0°, 232.350 мм |
| spear_10 | 2.8387 | 130.140 мм | 124.440 мм | 45°, 124.440 мм |

Обобщение про 45° ломается для `spear_9`: при 45° занимаемый квадрат немного больше, чем без поворота.

## 4. Укладка реального контура STL

Расчёт по bounding rectangle является консервативным. Реальная деталь не заполняет все четыре угла своего прямоугольника.

Поэтому дополнительно все XY-вершины каждого STL были повёрнуты на углы от 0 до 90°, после чего минимизирована максимальная из двух фактических ширин.

| Деталь | Оптимальный угол реального контура | Фактический минимальный квадрат | Влезает в 180×180 |
|---|---:|---:|---:|
| spear_7 | 55.199° | 180.406 мм | Нет, превышение 0.406 мм |
| spear_9 | 38.686° | 182.146 мм | Нет, превышение 2.146 мм |
| spear_10 | 32.925° | 106.589 мм | Да |

Это уточняет первоначальное утверждение:

- `spear_7` действительно не входит в номинальный стол 180×180, но не на 35 мм, как следует из прямоугольника 215 мм, а всего на 0.406 мм по идеальной геометрии;
- `spear_9` не входит на 2.146 мм;
- с практическими полями, purge line и допусками обе детали всё равно нельзя считать пригодными для A1 mini в текущем масштабе;
- оптимальный угол реального `spear_7` не 45°, поскольку сама деталь не прямоугольная.

На стол 256×256 все три входят. `spear_7` формально входит даже прямо: 251.05 мм оставляют 4.95 мм суммарного запаса, но это слишком мало для уверенной производственной печати. Поворот даёт заметно больший запас.

## 5. Площадь поверхности и средняя толщина

| Деталь | Объём, см³ | Площадь поверхности, см² | `2V/S`, мм |
|---|---:|---:|---:|
| spear_7 | 132.4035 | 283.9133 | 9.327 |
| spear_9 | 154.7026 | 422.3596 | 7.326 |
| spear_10 | 86.9459 | 208.0329 | 8.359 |

Для тонкой пластины:

\[
t_\text{эфф}\approx\frac{2V}{S}
\]

По этой оценке детали имеют характерную толщину порядка 7.3–9.3 мм.

Это тонко относительно общих габаритов, но не означает, что три периметра 0.4-мм соплом превратят весь объём почти в сплошной. Суммарная оболочка с двух противоположных сторон будет порядка 2.4–2.7 мм, а не 7–9 мм.

При этом локальные участки могут быть существенно тоньше среднего и печататься сплошными.

## 6. Расход TPU и масса

Заявленная формула:

\[
m=V\cdot0.36\cdot1.21
\]

На измеренных объёмах она даёт:

| Деталь | Масса по коэффициенту 0.36 |
|---|---:|
| spear_7 | 57.675 г |
| spear_9 | 67.388 г |
| spear_10 | 37.874 г |

Округлённые 58, 67 и 38 г арифметически получены правильно. Проблема не в арифметике, а в переносе коэффициента.

### Более физичная приближённая модель

Для оболочки эффективной толщины `δ`:

\[
V_\text{shell}\approx S\delta
\]

\[
f_\text{shell}\approx\frac{S\delta}{V}
\]

После этого 20% заполнения применяется только к оставшемуся внутреннему объёму:

\[
f_\text{material}=f_\text{shell}+(1-f_\text{shell})\cdot0.2
\]

Принята вилка:

\[
\delta=0.8\ldots1.35\text{ мм}
\]

Нижняя граница соответствует эффективной оболочке, ограниченной верхними/нижними слоями. Верхняя близка к трём линиям периметра для сопла 0.4 мм.

Результат:

| Деталь | Доля материала | Масса при 1.21 г/см³ | Заявлено |
|---|---:|---:|---:|
| spear_7 | 0.337–0.432 | **54–69 г** | 58 г |
| spear_9 | 0.375–0.495 | **70–93 г** | 67 г |
| spear_10 | 0.353–0.458 | **37–48 г** | 38 г |

Выводы:

- коэффициент 0.36 находится около нижней границы разумной оценки;
- для `spear_7` и `spear_10` заявленная масса возможна только при достаточно тонкой эффективной оболочке;
- наиболее вероятное занижение — у `spear_9`, потому что у неё максимальное отношение поверхности к объёму;
- средний коэффициент всего копья не должен применяться к отдельным деталям без проверки в слайсере.

Эти оценки не включают:

- поддержки;
- raft/brim;
- purge;
- калибровочные линии;
- отходы;
- возможное увеличение flow для TPU;
- локальные зоны, которые слайсер сделает полностью сплошными.

## 7. Итоговый вердикт

Перед печатью необходимо:

1. Переориентировать детали или сделать плоские технологические основания. Сейчас все шесть моделей касаются стола одной вершиной.
2. Отремонтировать дубли граней и неманифолдные рёбра в `spear_7_L/R` и `spear_10_L/R`.
3. Удалить/ретриангулировать вырожденные и почти вырожденные грани, особенно нулевой треугольник `spear_9`.
4. После ремонта повторно проверить замкнутость, объём и первый слой.
5. Получить расход материала реальным слайсом с конкретным профилем TPU.
6. Для стола 180×180 не использовать текущий масштаб `spear_7` и `spear_9` без дополнительного уменьшения и запаса.

## 8. Что не удалось определить точно

Без Bambu Studio/OrcaSlicer и конкретного профиля нельзя точно определить:

- массу;
- время печати;
- количество поддержек;
- пригодность отдельных нависаний;
- реальное заполнение локально тонких зон;
- поведение первого слоя;
- допустимые поля конкретного принтера.

Не заданы:

- точная модель Bambu Lab;
- диаметр сопла;
- высота слоя;
- ширины линий;
- число и толщина верхних/нижних слоёв;
- тип заполнения;
- параметры поддержек;
- brim/raft;
- профиль конкретного TPU.

## 9. Код проверки

Полный исполняемый код находится в соседнем файле [`audit_stl.py`](./audit_stl.py). Он выводит все результаты проверки в JSON.

Запуск из корня проекта:

```powershell
python .\audit_stl.py
```

Ключевые формулы расчёта:

```python
def signed_volume(triangles):
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0


def edge_incidence(mesh, decimals=6):
    vertices = np.round(mesh.vertices, decimals=decimals)
    _, inverse = np.unique(vertices, axis=0, return_inverse=True)
    faces = inverse[mesh.faces]
    edges = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])
    )
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return (
        int((counts == 1).sum()),
        int((counts == 2).sum()),
        int((counts > 2).sum()),
    )


def shell_mass_range(volume_cm3, area_cm2):
    estimates = {}
    for delta_mm in (0.8, 1.35):
        shell_fraction = min(
            1.0,
            area_cm2 * (delta_mm / 10.0) / volume_cm3,
        )
        material_fraction = (
            shell_fraction + (1.0 - shell_fraction) * 0.20
        )
        estimates[str(delta_mm)] = {
            "material_fraction": material_fraction,
            "mass_g": volume_cm3 * material_fraction * 1.21,
        }
    return estimates
```

## 10. Полный исходный код

```python
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from scipy.optimize import minimize_scalar


ROOT = Path(__file__).resolve().parent / "Lohen_Weapons" / "stl_tpu"
NAMES = [
    "spear_7_L.stl",
    "spear_7_R.stl",
    "spear_9_L.stl",
    "spear_9_R.stl",
    "spear_10_L.stl",
    "spear_10_R.stl",
]


def signed_volume(triangles: np.ndarray) -> float:
    """Oriented tetrahedron sum, in mm^3."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def edge_incidence(mesh: trimesh.Trimesh, decimals: int = 6) -> tuple[int, int, int]:
    """Counts boundary, manifold, and non-manifold undirected edges after weld."""
    vertices = np.round(mesh.vertices, decimals=decimals)
    _, inverse = np.unique(vertices, axis=0, return_inverse=True)
    faces = inverse[mesh.faces]
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((counts == 1).sum()), int((counts == 2).sum()), int((counts > 2).sum())


def unique_vertices(mesh: trimesh.Trimesh, decimals: int = 6) -> np.ndarray:
    return np.unique(np.round(mesh.vertices, decimals=decimals), axis=0)


def nearest_error(source: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    distance, _ = cKDTree(target).query(source, workers=-1)
    return float(np.sqrt(np.mean(distance**2))), float(distance.max())


def horizontal_section_area(mesh: trimesh.Trimesh, z_mm: float) -> float:
    """Area enclosed by all horizontal section loops, via shoelace."""
    section = mesh.section(plane_origin=[0.0, 0.0, z_mm], plane_normal=[0.0, 0.0, 1.0])
    if section is None:
        return 0.0
    total = 0.0
    for loop in section.discrete:
        points = np.asarray(loop)[:, :2]
        total += 0.5 * abs(
            np.dot(points[:-1, 0], points[1:, 1])
            - np.dot(points[:-1, 1], points[1:, 0])
        )
    return float(total)


def best_proper_rotation_error(left: np.ndarray, right: np.ndarray) -> dict:
    """Best set error over rotations allowed by distinct covariance eigenframes.

    Any exact rigid isometry between point sets maps covariance eigenvectors.
    With three distinct eigenvalues only the eight eigenvector sign choices remain.
    We retain determinant +1 candidates (proper rotations) and test point sets.
    """
    lp = left - left.mean(axis=0)
    rp = right - right.mean(axis=0)
    leval, levec = np.linalg.eigh(np.cov(lp, rowvar=False, bias=True))
    reval, revec = np.linalg.eigh(np.cov(rp, rowvar=False, bias=True))
    order_l = np.argsort(leval)[::-1]
    order_r = np.argsort(reval)[::-1]
    leval, levec = leval[order_l], levec[:, order_l]
    reval, revec = reval[order_r], revec[:, order_r]

    best = (math.inf, math.inf, None)
    for signs in itertools.product((-1.0, 1.0), repeat=3):
        rotation = levec @ np.diag(signs) @ revec.T
        if np.linalg.det(rotation) < 0.0:
            continue
        transformed = lp @ rotation + right.mean(axis=0)
        rms, maximum = nearest_error(transformed, right)
        if rms < best[0]:
            best = (rms, maximum, rotation)
    return {
        "rms_mm": best[0],
        "max_mm": best[1],
        "covariance_eigenvalues_L": leval.tolist(),
        "covariance_eigenvalues_R": reval.tolist(),
        "rotation_det": float(np.linalg.det(best[2])),
    }


def analyze(path: Path) -> tuple[trimesh.Trimesh, dict]:
    mesh = trimesh.load_mesh(path, force="mesh", process=False)
    welded = trimesh.load_mesh(path, force="mesh", process=True)
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    bounds = np.array((triangles.min(axis=(0, 1)), triangles.max(axis=(0, 1))))
    areas = trimesh.triangles.area(triangles)
    boundary, manifold, nonmanifold = edge_incidence(mesh)
    rounded = np.round(mesh.vertices, decimals=6)
    _, inverse = np.unique(rounded, axis=0, return_inverse=True)
    welded_faces = inverse[mesh.faces]
    unordered_faces = np.sort(welded_faces, axis=1)
    _, duplicate_counts = np.unique(unordered_faces, axis=0, return_counts=True)
    volume_signed = signed_volume(triangles)
    volume_abs = abs(volume_signed)
    surface = float(areas.sum())
    z_min = bounds[0, 2]
    at_bottom = np.isclose(triangles[:, :, 2], z_min, rtol=0.0, atol=1e-6)
    bottom_faces = np.all(at_bottom, axis=1)
    bottom_vertices = np.unique(
        np.round(triangles.reshape((-1, 3))[at_bottom.reshape(-1)], decimals=6), axis=0
    )
    result = {
        "file": path.name,
        "triangles": len(triangles),
        "bounds_min_mm": bounds[0].tolist(),
        "bounds_max_mm": bounds[1].tolist(),
        "size_mm": (bounds[1] - bounds[0]).tolist(),
        "bbox_center_mm": ((bounds[1] + bounds[0]) / 2.0).tolist(),
        "signed_volume_cm3": volume_signed / 1000.0,
        "trimesh_volume_cm3": float(mesh.volume) / 1000.0,
        "surface_area_cm2": surface / 100.0,
        "effective_slab_thickness_mm_2V_over_S": 2.0 * volume_abs / surface,
        "bottom_vertices_at_zmin": len(bottom_vertices),
        "bottom_coplanar_faces": int(bottom_faces.sum()),
        "bottom_coplanar_face_area_mm2": float(areas[bottom_faces].sum()),
        "horizontal_section_area_at_z_0.2_mm2": horizontal_section_area(welded, z_min + 0.2),
        "is_watertight_after_vertex_weld": bool(welded.is_watertight),
        "is_winding_consistent_after_vertex_weld": bool(welded.is_winding_consistent),
        "is_volume_after_vertex_weld": bool(welded.is_volume),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "manifold_edges": manifold,
        "duplicate_unoriented_face_groups": int((duplicate_counts > 1).sum()),
        "area_median_mm2": float(np.median(areas)),
        "area_min_mm2": float(areas.min()),
        "area_eq_0_mm2": int((areas == 0.0).sum()),
        "area_lt_1e-6_mm2": int((areas < 1e-6).sum()),
        "area_lt_1e-5_mm2": int((areas < 1e-5).sum()),
        "ten_smallest_areas_mm2": np.sort(areas)[:10].tolist(),
    }
    return mesh, result


def square_footprint(length: float, width: float) -> dict:
    if width > length:
        length, width = width, length
    diagonal = (length + width) / math.sqrt(2.0)
    best = min(length, diagonal)
    angle = 0.0 if length <= diagonal else 45.0
    return {
        "L_mm": length,
        "W_mm": width,
        "aspect_L_over_W": length / width,
        "straight_square_mm": length,
        "45deg_square_mm": diagonal,
        "optimal_angle_deg": angle,
        "minimum_square_mm": best,
        "fits_180": best <= 180.0,
        "fits_256": best <= 256.0,
    }


def actual_xy_footprint(mesh: trimesh.Trimesh) -> dict:
    """Minimum square enclosing the actual XY vertex set under rotation."""
    points = np.unique(np.round(mesh.vertices[:, :2], decimals=6), axis=0)

    def extents(theta: float) -> tuple[float, float]:
        cosine, sine = math.cos(theta), math.sin(theta)
        x = points[:, 0] * cosine - points[:, 1] * sine
        y = points[:, 0] * sine + points[:, 1] * cosine
        return float(np.ptp(x)), float(np.ptp(y))

    def objective(theta: float) -> float:
        return max(extents(theta))

    grid = np.linspace(0.0, math.pi / 2.0, 7201)
    values = np.array([objective(theta) for theta in grid])
    index = int(np.argmin(values))
    low = grid[max(0, index - 2)]
    high = grid[min(len(grid) - 1, index + 2)]
    optimum = minimize_scalar(
        objective, bounds=(low, high), method="bounded", options={"xatol": 1e-13}
    )
    width, height = extents(float(optimum.x))
    return {
        "optimal_angle_deg": math.degrees(float(optimum.x)),
        "rotated_size_mm": [width, height],
        "minimum_square_mm": max(width, height),
        "fits_180": max(width, height) <= 180.0,
        "fits_256": max(width, height) <= 256.0,
    }


def shell_mass_range(volume_cm3: float, area_cm2: float) -> dict:
    """First-order shell + 20% infill estimate, not a slicer simulation.

    delta is an effective inward solid skin.  0.8--1.35 mm spans typical
    top/bottom skin and three 0.4-mm-nozzle perimeter lines.
    """
    estimates = {}
    for delta_mm in (0.8, 1.35):
        shell_fraction = min(1.0, area_cm2 * (delta_mm / 10.0) / volume_cm3)
        material_fraction = shell_fraction + (1.0 - shell_fraction) * 0.20
        estimates[str(delta_mm)] = {
            "shell_fraction": shell_fraction,
            "material_fraction": material_fraction,
            "mass_g_at_TPU_1.21": volume_cm3 * material_fraction * 1.21,
        }
    return estimates


def main() -> None:
    meshes = {}
    output = {"files": [], "pairs": {}, "footprints": {}}
    for name in NAMES:
        mesh, result = analyze(ROOT / name)
        meshes[name] = mesh
        output["files"].append(result)

    for number in (7, 9, 10):
        lname = f"spear_{number}_L.stl"
        rname = f"spear_{number}_R.stl"
        left = unique_vertices(meshes[lname])
        right = unique_vertices(meshes[rname])
        reflected = left.copy()
        reflected[:, 0] *= -1.0
        mirror_rms, mirror_max = nearest_error(reflected, right)
        reverse_rms, reverse_max = nearest_error(right, reflected)
        output["pairs"][str(number)] = {
            "unique_vertices_L": len(left),
            "unique_vertices_R": len(right),
            "mirror_L_to_R_rms_mm": mirror_rms,
            "mirror_L_to_R_max_mm": mirror_max,
            "mirror_R_to_L_rms_mm": reverse_rms,
            "mirror_R_to_L_max_mm": reverse_max,
            "best_proper_rotation": best_proper_rotation_error(left, right),
        }

    by_name = {entry["file"]: entry for entry in output["files"]}
    for number in (7, 9, 10):
        entry = by_name[f"spear_{number}_L.stl"]
        size = entry["size_mm"]
        output["footprints"][str(number)] = square_footprint(size[0], size[1])
        output["footprints"][str(number)]["actual_mesh_xy"] = actual_xy_footprint(
            meshes[f"spear_{number}_L.stl"]
        )
        output["footprints"][str(number)]["shell_mass_range"] = shell_mass_range(
            abs(entry["signed_volume_cm3"]), entry["surface_area_cm2"]
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

```
