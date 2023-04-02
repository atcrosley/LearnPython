# suppose that a machine sells bottles of Coca-Cola for 50 cents and only accepts coins in these denominations: 25 cents, 10 cents, and 5 cents. The program promps the user to insert a coin and returns the amount due. Once you reach 50 output how many cents in change the user is owed. Assume that the user will only input integers. Ignore integer that isn't an accepted denomination

def cokemachine():
    coke = 50
    while coke > 0:
        x = int(input("Insert coin:"))
        coke -= x
        if coke > 0:
            print("Amount due: ", abs(coke))
            continue
        else:
            print("Amount owed ", abs(coke))
            break


cokemachine()
