# [-5, -3, -1, 2, 4] -> [1, 4, 9, 16, 25]

def fun(arr):
    m = arr.index(min(arr, key=abs))
    left = m - 1
    right = m + 1
    result = [arr[m] ** 2]
    for i in range(len(arr) - 1):
        try:
            if abs(arr[left]) < abs(arr[right]):
                result.append(arr[left] ** 2)
                left -= 1
                left = None if left < 0 else left
            elif abs(arr[left]) > abs(arr[right]):
                result.append(arr[right] ** 2)
                right += 1
                right = None if right == len(arr) else right
        except TypeError:
            if left is None:
                result.append(arr[right] ** 2)
                right += 1
            elif right is None:
                result.append(arr[left] ** 2)
                left -= 1
    return result


print(fun([-5, -3, -1, 2, 4]))
