def route(d, hop, start_pos, end_pos):
    result = {start_pos: {'x': d[start_pos]['x'], 'y': d[start_pos]['y']}}
    start_city = int(start_pos)
    start_pos = int(d[int(start_pos)]['x']), int(d[int(start_pos)]['y'])
    del d[start_city]
    end_pos = int(d[int(end_pos)]['x']), int(d[int(end_pos)]['y'])
    distance = get_distance_between(start_pos, end_pos)
    if distance == int(hop):
        return 1
    for item in d:
        current_pos = int(d[item]['x']), int(d[item]['y'])
        current_distance = get_distance_between(start_pos, current_pos)
        if current_distance <= int(hop):
            for j in d:
                if j == item:
                    continue
                print((int(d[j]['x']), int(d[j]['y'])))
                if get_distance_between(current_pos, (int(d[j]['x']), int(d[j]['y']))) <= int(hop):
                    print(get_distance_between(current_pos, (int(d[j]['x']), int(d[j]['y']))), current_pos, j)


def get_distance_between(a, b):
    return abs(a[0]-b[0]) + abs(a[1]-b[1])


def get_route(previous_pos, current_pos, hop, end_pos, coordinates):
    pass


with open('input.txt', 'r') as reader:
    count = reader.readline().strip()
    cities = {}
    for n, i in enumerate(range(int(count)), start=1):
        pos = reader.readline().strip()
        cities[n] = {'x': pos.split(' ')[0], 'y': pos.split(' ')[1]}
    k = reader.readline().strip()
    start = reader.readline().strip()
    end, start = start.split(' ')[1], start.split(' ')[0]

route(cities, k, start, end)

with open('output.txt', 'w') as writer:
    writer.write('result')